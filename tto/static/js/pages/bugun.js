// Bugün: the morning screen - what wants attention, on one page (/api/bugun, tto/bugun.py): the RET, the open trades
// (their P&L as of the last "MTM yenile": nothing is valued here), the quant's new AL / SAT lines, the DİBS bonds whose
// signal turned, the chat's trades not entered, today's agenda and meetings.  Every block leads to where its thing is
// handled and says plainly when there is nothing.  Read again with the market's generations (at most every 20 s), when
// the agenda or the trades change (the live stream's counters) and with "Yenile"; "Açılış sayfası yap" makes it the page
// the dashboard opens on.
// The blocks stand in columns, the things to do first (the desk, 27.11.2026: "Hepsini yap" - the layout proposals): RET,
// the checks, the chat's trades not entered and the agenda in the first column, then the morning meeting and the trades,
// the quant's lines and the DİBS bonds last; a block never leaves a hole beside a taller one, and a table's column that is
// empty in every row goes.
// The morning meeting (the desk, 28.11.2026: "A - Yildizlilari yap. B - Hepsini yap. C - 2-3-4-5-8-10-12-13-16"): the checks
// of Masa's Kontrol strip that are not "tamam" and when the DV01 position was pasted (A10, A8), the PPK / FOMC day (C5),
// what moved since the close with one "Referansı şimdi al" for İzleme and Eğri Hareketi (A11), the desk's notes typed in
// place (A11); the quant's lines in two short lines each, their levels on screen (B19), the sides coloured as Günlük
// İşlemler colours them - RECEIVE / AL green, PAY / SAT red (B6); the notes two lines, "devamı" the rest.
import { api } from '../api.js';
import { h, clear, toast, errorToast, foldNote } from '../ui.js';
import { num, isoToTr } from '../format.js';
import { landing, setLanding } from '../layout.js';
import { level } from './broker.js';
import { bondCardLinks } from '../bonds.js';
import { setupGoLinks } from '../golink.js';

// (the dashboard's own links in tables - Masa's Kontrol chips - are followed from here: this module is loaded with the app)
setupGoLinks();

const EVERY = 20000;               // ms: the market's generations read the page again at most this often
/** The blocks in the order they are read: the things to do first. */
export const ORDER = ['ret', 'kontrol', 'chat', 'agenda', 'meeting', 'moves', 'notes', 'trades', 'quant', 'dibs'];
const COL_MIN = 480;               // px: a column is never narrower (fewer columns instead)
const GAP = 12;

/** How many columns a page this wide takes (1 to 3). */
export function columnCount(width) {
  return Math.max(1, Math.min(3, Math.floor((width + GAP) / (COL_MIN + GAP))));
}

/** The blocks of each column for ``n`` columns: the things to do together in the first, the morning meeting next, the
 *  quant's lines and the DİBS bonds in the last. */
export function columnPlan(n) {
  if (n >= 3) return [['ret', 'kontrol', 'chat', 'agenda'], ['meeting', 'moves', 'notes', 'trades'], ['quant', 'dibs']];
  if (n === 2) return [['ret', 'kontrol', 'chat', 'agenda', 'meeting'], ['moves', 'notes', 'trades', 'quant', 'dibs']];
  return [ORDER.slice()];
}

const EMPTY_TEXT = new Set(['', '—', '–', '-']);

/** A column of a plain table whose every row (the header and a total aside) is empty goes: [its index, ...]. */
export function emptyColumns(rows) {
  const body = rows.filter((r) => !r.head && !r.sum);
  if (!body.length) return [];
  const n = Math.max(...rows.map((r) => r.cells.length));
  const out = [];
  for (let j = 0; j < n; j++) if (body.every((r) => EMPTY_TEXT.has(String(r.cells[j] === undefined ? '' : r.cells[j]).trim()))) out.push(j);
  return out;
}

/** A trade's side coloured as Günlük İşlemler colours it (the desk, 28.11.2026: B6): RECEIVE / AL (a receive, a buy) green
 *  ("buy"), PAY / SAT red ("sell"), a spread's or a fly's way (STEEPENER, FLATTENER …) neither. */
export function sideClass(side) {
  const s = String(side || '').trim().toUpperCase();
  if (/^(RECEIVE|REC\b|REC GÖVDE|AL\b|ALIŞ|KORUMA AL)/.test(s)) return 'buy';
  if (/^(PAY\b|PAY GÖVDE|SAT\b|SATIŞ|KORUMA SAT)/.test(s)) return 'sell';
  return '';
}

/** A quant line's levels as one short line (B19): "34,445 → 34,000 · stop 34,700 · R/R 1,59". */
export function levelsLine(x) {
  const p = (v) => (isNum(v) ? num(v, x.digits) : '—');
  return p(x.entry) + ' → ' + p(x.target) + ' · stop ' + p(x.stop) + (isNum(x.rr) ? ' · R/R ' + num(x.rr, 2) : '');
}

/** A meeting decision typed after it (C5: "Karar" - the step decided, bp): the surprise against the priced step and the
 *  position's P&L of it (its risk of the decision, TL/bp) - ``null`` when either is not known. */
export function surprise(decided, implied, perBp) {
  if (!isNum(decided) || !isNum(implied)) return null;
  const s = decided - implied;
  return { bp: s, pnl: isNum(perBp) ? s * perBp : null };
}

/** Take the empty columns out of a table drawn (``tr`` of ``th`` / ``td``, no spans). */
function dropEmptyColumns(table) {
  const trs = [...table.querySelectorAll('tr')];
  const rows = trs.map((tr) => ({ head: !!tr.querySelector('th'), sum: tr.classList.contains('sum'), cells: [...tr.children].map((c) => c.textContent) }));
  const gone = emptyColumns(rows);
  if (!gone.length || gone.length >= rows[0].cells.length) return;
  for (const tr of trs) for (const j of gone.slice().reverse()) if (tr.children[j]) tr.children[j].remove();
}

const isNum = (v) => typeof v === 'number' && isFinite(v);
const sgn = (v, d = 0) => (isNum(v) ? (v > 0 ? '+' : '') + num(v, d) : '—');
/** A level of a trade (a rate, a spread, a price) with the decimals it has: 2 at least, 4 at most. */
function lvl(v) {
  let d = 2;
  while (d < 4 && Math.abs(v * 10 ** d - Math.round(v * 10 ** d)) > 1e-7) d += 1;
  return num(v, d, false);
}
const cls = (v) => (isNum(v) && Math.abs(v) >= 0.5 ? (v > 0 ? 'pos' : 'neg') : '');
/** "2026-11-17 09:12:33" -> "09:12" today, "16.11.2026 17:40" another day. */
function stamp(text, today) {
  const s = String(text || '');
  if (!s) return '';
  return (s.slice(0, 10) === today ? '' : isoToTr(s.slice(0, 10)) + ' ') + s.slice(11, 16);
}
const none = (text, id) => h('div', { class: 'bugun-none', id: id || null }, text);
/** A block's note: two lines, "devamı" the rest (the desk, 28.11.2026: the notes folded on Bugün). */
function note(text, id) {
  const el = h('div', { class: 'muted bugun-note', id: id || null }, text);
  foldNote(el);
  return el;
}
const td = (text, c, title) => h('td', { class: c || null, title: title || null }, text);
const KARAR_KEY = 'tto.bugun.karar.';

/** A signal of DİBS RV as the block says it: "PAHALI → UCUZ (+12,4 bp)", or the state alone without a comparison. */
function sigText(x) {
  const word = (s) => s || '–';
  const v = isNum(x.v) ? ' (' + sgn(x.v, 1) + ' bp)' : '';
  if (x.known && (x.prev || '') !== (x.now || '')) return word(x.prev) + ' → ' + word(x.now) + v;
  if (x.now === null || x.now === undefined) return '—';
  return word(x.now) + v;
}
const sigClass = (x) => (x.now === 'UCUZ' ? 'buy' : x.now === 'PAHALI' ? 'sell' : 'muted')
  + (x.known && (x.prev || '') !== (x.now || '') ? ' turned' : '');

/** A chat line's trade: "18M @ 35,14", "DİBS 15.03.28 @ 100,550". */
function chatWhat(q) {
  q = q || {};
  const inst = q.product === 'OIS' ? q.label : (q.product === 'DIBS' ? 'DİBS ' + q.label : (q.product || '') + ' ' + (q.label || ''));
  return (inst || '').trim() + (isNum(q.price) ? ' @ ' + level(q.price, q.unit) : '');
}

export class BugunPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.data = null;
    this.reading = false;
    this.again = false;
    this.last = 0;
    this.timer = null;
    this.cards = {};
  }

  async load() {
    this.build();
    await this.reload();
  }

  /** The market moved: read again - at most every EVERY ms (one later read is kept for then). */
  refresh() {
    const wait = this.last + EVERY - Date.now();
    if (wait <= 0) return this.reload();
    if (!this.timer && !this.dead) this.timer = setTimeout(() => { this.timer = null; this.reload().catch(() => {}); }, wait);
    return Promise.resolve();
  }

  /** The live stream's counters: the agenda or the trades changed somewhere (another trader, another window). */
  onDesk(changed) {
    if (changed.includes('agenda') || changed.includes('trades')) this.reload().catch(() => {});
  }

  destroy() {
    this.dead = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.resize) this.resize.disconnect();
  }

  /** One reading at a time; a change meanwhile reads once more after it. */
  async reload() {
    if (this.reading) { this.again = true; return; }
    this.reading = true;
    try {
      do {
        this.again = false;
        const d = await api.get('/api/bugun');
        this.last = Date.now();
        if (this.dead) return;
        this.data = d;
        this.paint();
      } while (this.again && !this.dead);
    } finally {
      this.reading = false;
    }
  }

  // ------------------------------------------------------------------ the page
  build() {
    clear(this.host);
    const again = h('button', { class: 'btn sm', type: 'button', id: 'bugun-refresh', title: 'Şimdi yeniden oku (sayfa piyasayla en çok 20 sn\'de bir kendiliğinden okunur)' }, 'Yenile');
    again.addEventListener('click', () => this.reload().catch(errorToast));
    this.stamp = h('span', { class: 'muted', id: 'bugun-time' });
    this.landingBox = h('span', { class: 'bugun-landing', id: 'bugun-landing' });
    this.host.appendChild(h('div', { class: 'page-tools' }, again, this.stamp, h('span', { class: 'grow' }), this.landingBox));
    this.grid = h('div', { class: 'bugun-grid bugun-cols', id: 'bugun' });
    this.host.appendChild(this.grid);
    const card = (key, title, link, tip, go, extra) => {
      const count = h('span', { class: 'bugun-count hidden', id: 'bugun-' + key + '-count' });
      const btn = h('button', { class: 'btn sm', type: 'button', id: 'bugun-' + key + '-go', title: tip }, link + ' →');
      btn.addEventListener('click', go);
      const body = h('div', { class: 'bugun-body', id: 'bugun-' + key + '-body' });
      const el = h('section', { class: 'panel bugun-card', id: 'bugun-' + key }, h('header', null, h('h2', null, title), count, extra || null, btn), body);
      this.cards[key] = { el, body, count };
    };
    const hash = (x) => () => { window.location.hash = '#/' + x; };
    card('ret', 'RET', 'RET penceresi', 'RET faizleri penceresi: yüklenmediyse elle giriş, güncelleme varsa adil değer sekmesinde açılır',
      () => this.openRet());
    card('kontrol', 'Kontrol · sabah', 'Masa', 'Masa · Genel bakış: Kontrol şeridi (her çip kontrol ettiği tabloya götürür)', hash('masa'));
    card('trades', 'Trades · açık işlemler', 'Trades', 'Trades sayfası: MTM yenile, işlemler, kapanış', hash('trades'));
    card('quant', 'Quant · yeni AL / SAT', 'Sinyaller', 'Quant › Sinyaller: bütün liste, kartlar, kayıt', hash('quant'));
    card('dibs', 'DİBS · sinyali dönen kâğıtlar', 'DİBS Trading', 'DİBS Trading · özet (kâğıt tablosunun tek evi): trading listesinin kâğıtları OIS ASW, FX swap ASW ve sıfır kupon eğrisine göre',
      hash('dibslive?p=L0'));
    card('chat', 'Girilmemiş işlemler', 'Chat ↔ Günlük İşlemler', 'Masanın chat\'teki işlemleri Günlük İşlemler\'in yanında: eşleştir, yok say, gir',
      () => this.ctx.openRecon().catch(errorToast));
    card('agenda', 'Ajanda · takvim', 'Ajanda', 'Ajanda: bugünün işleri, deadline\'lar, tekrarlayan işler', hash('agenda'));
    card('meeting', 'PPK / FOMC günü', 'DV01 Risk', 'DV01 Risk › PPK karar riski: pozisyonun her toplantının kararına riski', hash('dv01?p=B9'));
    // one reference for İzleme and Eğri Hareketi (A11): the levels now - each page tells its changes since then
    const ref = h('button', { class: 'btn sm', type: 'button', id: 'bugun-ref',
      title: 'İzleme\'deki kalemlerin ve Eğri Hareketi\'nin noktalarının şimdiki seviyesini referans al (sabah toplantısı): iki sayfa da değişimi bundan beri gösterir' },
    'Referansı şimdi al');
    ref.addEventListener('click', () => this.takeReference());
    card('moves', 'Kapanıştan beri', 'Eğri Hareketi', 'Eğri Hareketi: her noktanın önceki kapanışa, açılışa ya da referansa göre değişimi', hash('heat'), ref);
    card('notes', 'Masa notları · bugün', 'İzleme', 'İzleme · Alarmlar: aynı notlar, alarmlar, izleme listesi', hash('watch'));
    this.cards.meeting.el.classList.add('hidden');            // (only on a meeting's day and the day before it)
    this.columns = 0;
    this.arrange();
    // the columns follow the page's width (the menu folded, the side drawer opened, the window resized)
    if (typeof ResizeObserver === 'function') {
      this.resize = new ResizeObserver(() => this.arrange());
      this.resize.observe(this.grid);
    }
  }

  /** The blocks into their columns (only when the number of columns changes: a block keeps its place). */
  arrange() {
    const n = columnCount(this.grid.clientWidth || this.host.clientWidth || 1600);
    if (n === this.columns) return;
    this.columns = n;
    clear(this.grid);
    for (const keys of columnPlan(n)) {
      const col = h('div', { class: 'bugun-col' });
      for (const k of keys) if (this.cards[k]) col.appendChild(this.cards[k].el);
      this.grid.appendChild(col);
    }
  }

  openRet(tab) {
    const t = tab || (this.data && this.data.ret && this.data.ret.tab) || null;
    this.ctx.openRet(t ? { tab: t } : undefined);
  }

  async takeReference() {
    try {
      const r = await api.post('/api/watch/reference', {});
      toast('Referans alındı (' + r.at + '): İzleme\'de ' + r.taken + ' kalem, Eğri Hareketi\'nde ' + r.count + ' nokta', 'ok', 5000);
      this.reload().catch(() => {});
    } catch (err) { errorToast(err); }
  }

  paint() {
    const d = this.data;
    if (!d) return;
    this.stamp.textContent = isoToTr(d.today) + ' · ' + d.time + ' itibarıyla';
    this.paintLanding();
    const painters = { ret: this.paintRet, kontrol: this.paintKontrol, trades: this.paintTrades, quant: this.paintQuant,
      dibs: this.paintDibs, chat: this.paintChat, agenda: this.paintAgenda, meeting: this.paintMeeting, moves: this.paintMoves,
      notes: this.paintNotes };
    for (const key of ORDER) {
      const fn = painters[key];
      const c = this.cards[key];
      const x = d[key] || {};
      if (!c) continue;
      if (key === 'notes' && !x.error && x.available !== false) {
        // (typed in place: the box is kept while it is being typed into - it is never drawn again under the cursor)
        try { fn.call(this, c, x, d); } catch (err) { errToBody(c, err); }
        continue;
      }
      if (key === 'notes') c.notes = null;                      // (its box is drawn anew once it can be read again)
      clear(c.body);
      c.count.classList.add('hidden');
      c.el.classList.remove('bugun-attn');
      if (key === 'meeting') c.el.classList.toggle('hidden', !x.error && !(x.items || []).length);   // (a meeting's day only)
      if (x.error) { c.body.appendChild(h('div', { class: 'err' }, 'Okunamadı: ' + x.error.replace(/^okunamadı: /, ''))); continue; }
      if (x.available === false) { c.body.appendChild(none('Bu dashboard\'da yok (çalışma kitabı yüklü değil).')); continue; }
      try {
        fn.call(this, c, x, d);
        for (const t of c.body.querySelectorAll('table.plain.bugun')) dropEmptyColumns(t);      // (e.g. "Sıfır kupon" all "—")
      } catch (err) { errToBody(c, err); }
    }
  }

  /** A number beside a card's title (what needs a look), lit when it wants attention. */
  setCount(c, n, attn) {
    c.count.textContent = String(n);
    c.count.classList.toggle('hidden', !n);
    c.el.classList.toggle('bugun-attn', !!(n && attn));
  }

  paintLanding() {
    clear(this.landingBox);
    if (landing() === 'bugun') {
      this.landingBox.appendChild(h('span', { class: 'muted', title: 'Değiştirmek için: sağ üstteki adınız → Açılış sayfası…' }, 'Açılış sayfanız'));
      return;
    }
    const b = h('button', { class: 'btn sm', type: 'button', id: 'bugun-make-landing',
      title: 'Dashboard\'u adres yazmadan açtığınızda bu sayfa gelsin (hesabınızla saklanır; sağ üstteki adınız → Açılış sayfası… ile değişir)' },
    'Açılış sayfası yap');
    b.addEventListener('click', () => {
      setLanding('bugun').then(() => { toast('Açılış sayfanız: Bugün', 'ok'); this.paintLanding(); }, () => {});
    });
    this.landingBox.appendChild(b);
  }

  // ------------------------------------------------------------------ the blocks
  paintRet(c, r, d) {
    const b = c.body;
    const who = r.by ? ' · ' + r.by : '';
    if (r.loaded) {
      b.appendChild(h('div', { class: 'bugun-line ok', id: 'bugun-ret-state' }, h('b', null, 'Bugün yüklendi'), ' · ' + stamp(r.at, d.today) + who));
    } else {
      b.appendChild(h('div', { class: 'bugun-line warn', id: 'bugun-ret-state' }, h('b', null, 'Bugün yüklenmedi'),
        r.at ? ' · son yükleme ' + stamp(r.at, d.today) + who : ' · hiç yüklenmedi: dosyadaki değerler kullanılıyor'));
    }
    if (r.updates && r.updates.length) {
      const line = h('div', { class: 'bugun-line warn bugun-link', id: 'bugun-ret-updates', role: 'button', tabindex: '0',
        title: 'Adil değer yayınlanan RET\'ten farklı: bakmak ve "Kopyala ve yayınla" için tıklayın (yayınlamak sizin elinizde)' },
      h('b', null, 'RET güncellemesi var: '), r.updates.join(', '));
      line.addEventListener('click', () => this.openRet('fair'));
      line.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.openRet('fair'); } });
      b.appendChild(line);
    } else {
      b.appendChild(none('Adil değer yayınlanan RET\'le aynı: güncelleme yok' + (r.checked ? ' (' + r.checked + ' itibarıyla)' : '') + '.', 'bugun-ret-none'));
    }
    this.setCount(c, (r.loaded ? 0 : 1) + (r.updates || []).length, true);
  }

  /** Masa's checks that are not "tamam" - each leads to the table it checks, its rule in its tooltip (A10) - and when the
   *  DV01 position was pasted, red when not today (A8). */
  paintKontrol(c, k, d) {
    const b = c.body;
    const p = k.dv01 || {};
    const pasteTip = p.at ? 'DV01 Risk pozisyonu (VaR sekmesindeki Onshore / TLREF / Offshore, Pozisyon\'daki C) en son ' + p.at + '\'te yazıldı'
      : 'DV01 Risk pozisyonu yapıştırılmadı: Murex\'in Onshore / TLREF kolonlarını DV01 Risk › VaR sekmesine yapıştırın';
    b.appendChild(h('div', { class: 'bugun-line ' + (p.today ? 'ok' : 'warn'), id: 'bugun-kontrol-dv01', title: pasteTip },
      h('b', null, 'DV01 pozisyonu: '), h('a', { href: '#/dv01?p=V3' }, p.at ? p.text + (p.today ? '' : ' · bugün değil') : 'yapıştırılmadı')));
    let bad = p.today ? 0 : 1;
    if (k.error_checks) {
      b.appendChild(h('div', { class: 'err' }, 'Kontrol şeridi okunamadı: ' + k.error_checks));
    } else if (k.checks) {
      if (k.checks.length) {
        const ul = h('ul', { class: 'bugun-checks', id: 'bugun-kontrol-list' });
        for (const x of k.checks) {
          const tone = x.code === 1 ? 'warn' : 'neg';
          ul.appendChild(h('li', { class: tone, title: x.rule + (x.where ? '\nTıklayın → ' + x.where : '') },
            x.href ? h('a', { href: x.href }, x.text || x.name) : (x.text || x.name), x.where ? h('span', { class: 'muted' }, ' · ' + x.where) : null));
        }
        b.appendChild(ul);
        bad += k.checks.length;
      }
      b.appendChild(h('div', { class: 'muted bugun-line', id: 'bugun-kontrol-ok', title: (k.ok || []).join(', ') },
        k.checks.length ? (k.ok || []).length + ' tamam' : 'Kontrollerin hepsi tamam (' + (k.ok || []).length + ').'));
    }
    this.setCount(c, bad, true);
  }

  /** A PPK / FOMC meeting today or on the next business day (C5): what it is priced at, against the last close, the survey
   *  and the scenarios, the position's risk of the decision; on the day "Karar": the surprise and its P&L. */
  paintMeeting(c, m, d) {
    const items = m.items || [];
    c.el.classList.toggle('hidden', !items.length);
    if (!items.length) return;
    const b = c.body;
    for (const x of items) {
      const box = h('div', { class: 'bugun-meeting', 'data-cal': x.cal, id: 'bugun-meeting-' + x.cal });
      box.appendChild(h('div', { class: 'bugun-line warn' }, h('b', null, x.name + ' · ' + isoToTr(x.date) + (x.when === 'today' ? ' · bugün' : ' · yarın'))));
      const implied = isNum(x.implied) ? sgn(x.implied, 1) + ' bp' : '—';
      if (x.cal === 'ppk') {
        const prev = x.prev ? ' · dünden ' + sgn(x.change, 1) + ' bp (' + isoToTr(x.prev.day) + ' kapanışı ' + sgn(x.prev.step, 1) + ')' : ' · dünle kıyas yok (PPK geçmişi)';
        box.appendChild(h('div', { class: 'bugun-line' }, 'İma adım: ', h('b', null, implied), (isNum(x.band) ? ' (± ' + num(x.band, 1) + ')' : '') + prev));
        if (x.survey) box.appendChild(h('div', { class: 'bugun-line' }, 'Anket: %' + num(x.survey.rate, 2) + (isNum(x.survey.step) ? ' (' + sgn(x.survey.step, 0) + ' bp)' : '')));
      } else {
        box.appendChild(h('div', { class: 'bugun-line' }, 'İma adım: ', h('b', null, implied), isNum(x.steps) ? ' (' + num(x.steps, 2) + ' adım)' : '',
          isNum(x.wirp) ? ' · WIRP farkı ' + sgn(x.wirp, 1) + ' bp' : '', isNum(x.vs_expected) ? ' · beklenenden ' + sgn(x.vs_expected, 1) + ' bp' : ''));
      }
      const sc = (x.scenarios || []).filter((s) => isNum(s.step));
      if (sc.length) {
        box.appendChild(h('div', { class: 'bugun-line muted' }, 'Senaryolar: ' + sc.map((s) => s.name + (isNum(s.prob) ? ' %' + num(s.prob * 100, 0) : '')
          + ' ' + sgn(s.step, 0)).join(' · ') + ' bp'));
      }
      if (x.risk) {
        box.appendChild(h('div', { class: 'bugun-line' }, 'Pozisyonunuz: karar riski ', h('b', { class: cls(x.risk.per_bp) }, sgn(x.risk.per_bp, 0) + ' TL/bp'),
          ' · 25 bp sürpriz ', h('b', { class: cls(x.risk.pnl25) }, sgn(x.risk.pnl25, 0) + ' TL')));
      }
      if (x.when === 'today') box.appendChild(this.decisionBox(x));
      b.appendChild(box);
    }
    this.setCount(c, items.length, true);
  }

  /** "Karar" (after the decision): the step decided, typed (kept in this browser for the day) - the surprise against the
   *  priced step and, for the PPK, the position's P&L of it (its risk of the decision × the surprise: DV01 Risk's
   *  "Tek toplantı sürprizi"). */
  decisionBox(x) {
    const key = KARAR_KEY + x.cal + '.' + x.date;
    let kept = '';
    try { kept = localStorage.getItem(key) || ''; } catch (e) { kept = ''; }
    const inp = h('input', { class: 'inp sm', type: 'text', id: 'bugun-karar-' + x.cal, value: kept, placeholder: 'adım, bp (örn. -150)', size: '12' });
    const out = h('span', { class: 'bugun-karar-out', id: 'bugun-karar-' + x.cal + '-out' });
    const show = () => {
      const v = parseFloat(String(inp.value).replace('−', '-').replace(',', '.'));
      clear(out);
      const s = surprise(v, x.implied, x.risk ? x.risk.per_bp : null);
      if (!s) { out.textContent = inp.value.trim() ? 'okunamadı' : ''; return; }
      out.appendChild(document.createTextNode(' → sürpriz ' + sgn(s.bp, 1) + ' bp'));
      if (isNum(s.pnl)) out.appendChild(h('b', { class: cls(s.pnl) }, ' · K/Z ' + sgn(s.pnl, 0) + ' TL'));
    };
    inp.addEventListener('input', () => {
      try { localStorage.setItem(key, inp.value); } catch (e) { /* not kept */ }
      show();
    });
    show();
    return h('div', { class: 'bugun-line bugun-karar', title: 'Karardan sonra açıklanan adımı yazın: ima adıma göre sürpriz ve pozisyonun bundan K/Z\'si (bu tarayıcıda gün boyu kalır)' },
      h('b', null, 'Karar: '), inp, out);
  }

  /** What moved since the previous close (A11): the largest moves, the points that did not move today, the alarms that
   *  fired since the close. */
  paintMoves(c, mv, d) {
    const b = c.body;
    const since = mv.since ? isoToTr(mv.since.slice(0, 10)) + ' ' + mv.since.slice(11) : '';
    b.appendChild(note((mv.closed ? 'Hafta sonu, piyasa kapalı: son iş günü ' + isoToTr(mv.closed) + ' kapanışı. ' : '')
      + 'Önceki kapanışa' + (mv.base_day ? ' (' + isoToTr(mv.base_day) + ')' : '') + ' göre en büyük ' + ((mv.top || []).length || '') + ' hareket: OIS, offshore, '
      + 'offshore − OIS, VİOP ve DİBS ASW (Eğri Hareketi\'nin noktaları, bp)' + (mv.ref_at ? ' · referansınız ' + mv.ref_at : ' · bugün referans alınmadı') + '.', 'bugun-moves-note'));
    const top = mv.top || [];
    if (top.length) {
      const table = h('table', { class: 'plain bugun', id: 'bugun-moves-table' });
      table.appendChild(h('tr', null, h('th', { class: 'l' }, 'Nokta'), h('th', null, 'Şimdi'), h('th', null, 'Kapanış'), h('th', null, 'Değişim')));
      for (const x of top) {
        table.appendChild(h('tr', null, td(x.label, 'l'), td(x.now_text), td(x.base_text, 'muted'),
          td(x.chg_text, x.chg > 0 ? 'up' : 'down')));
      }
      b.appendChild(table);
    } else {
      b.appendChild(none(mv.available === false ? 'Eğri Hareketi okunamadı.' : 'Önceki kapanışa göre hareket eden nokta yok.', 'bugun-moves-none'));
    }
    const still = mv.still || [];
    if (still.length) {
      b.appendChild(h('div', { class: 'bugun-line muted', id: 'bugun-moves-still', title: still.slice(0, 40).join(', ') + (still.length > 40 ? ' …' : '') },
        'Bugün kıpırdamayan nokta: ' + still.length + ' (kapanıştaki seviyesinde)'));
    }
    const al = mv.alarms || [];
    b.appendChild(h('div', { class: 'bugun-sub' }, 'Kapanıştan' + (since ? ' (' + since + ')' : '') + ' beri çalan alarmlar'));
    if (al.length) {
      b.appendChild(h('ul', { class: 'bugun-items', id: 'bugun-moves-alarms' }, ...al.map((a) => h('li', null,
        h('span', { class: 'muted' }, (a.day !== d.today ? isoToTr(a.day) + ' ' : '') + a.time), ' ', h('b', null, a.label),
        a.text ? ' · ' + a.text : '', a.value ? ' · ' + a.value : '', a.desk ? h('span', { class: 'muted' }, ' · Masa') : null))));
    } else {
      b.appendChild(none('Kapanıştan beri çalan alarm yok.', 'bugun-moves-noalarm'));
    }
    this.setCount(c, al.length, false);
  }

  /** The desk's notes of the day, typed in place (A11) - the same as İzleme's; the last earlier day's one click away. */
  paintNotes(c, n, d) {
    if (!c.notes) {
      const b = c.body;
      clear(b);
      const area = h('textarea', { class: 'inp chatbox', id: 'bugun-notes-text', rows: '4', spellcheck: 'false',
        placeholder: 'Bugün izlenecek seviyeler, sabah toplantısı, ihale, veri takvimi… (herkes görür)' });
      const info = h('span', { class: 'muted', id: 'bugun-notes-info' });
      const save = h('button', { class: 'btn sm primary', type: 'button', id: 'bugun-notes-save', title: 'Kaydet (Ctrl+Enter)' }, 'Kaydet');
      const prevBtn = h('button', { class: 'btn sm hidden', type: 'button', id: 'bugun-notes-prev' }, 'Dünkü notlar');
      const prevBox = h('div', { class: 'bugun-notes-prev hidden', id: 'bugun-notes-prevtext' });
      const st = { area, info, prevBtn, prevBox, dirty: false };
      area.addEventListener('input', () => { st.dirty = true; });
      const doSave = async () => {
        try {
          const r = await api.post('/api/notes', { text: area.value });
          st.dirty = false;
          info.textContent = 'Kaydedildi · ' + r.at;
          toast('Masa notları kaydedildi', 'ok');
        } catch (err) { errorToast(err); }
      };
      save.addEventListener('click', doSave);
      area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSave(); } });
      prevBtn.addEventListener('click', () => {
        const open = prevBox.classList.toggle('hidden') === false;
        prevBtn.classList.toggle('on', open);
      });
      b.appendChild(area);
      b.appendChild(h('div', { class: 'chatrow actions' }, save, info, h('span', { class: 'grow' }), prevBtn));
      b.appendChild(prevBox);
      c.notes = st;
    }
    const st = c.notes;
    const today = n.today || {};
    if (document.activeElement !== st.area && !st.dirty) st.area.value = today.text || '';
    if (!st.dirty) st.info.textContent = today.at ? 'Son kaydeden: ' + (today.by || '') + ' · ' + today.at : '';
    const prev = n.prev;
    st.prevBtn.classList.toggle('hidden', !prev);
    if (prev) {
      st.prevBtn.textContent = 'Dünkü notlar (' + isoToTr(prev.day).slice(0, 5) + ')';
      st.prevBtn.title = isoToTr(prev.day) + (prev.by ? ' · ' + prev.by : '') + (prev.at ? ' · ' + prev.at : '');
      st.prevBox.textContent = prev.text;
    }
  }

  paintTrades(c, t, d) {
    const b = c.body;
    const tabs = t.tabs || {};
    const mtm = (x, label) => {
      if (!x) return label + ': —';
      return label + ': ' + (x.mtm_at ? 'MTM ' + stamp(x.mtm_at, d.today) + (x.mtm_by ? ' (' + x.mtm_by + ')' : '')
        + (x.stale ? ', sonra değişiklik var' : '') : 'MTM yok');
    };
    b.appendChild(note(mtm(tabs.personal, 'Kişisel') + ' · ' + mtm(tabs.desk, 'Masa')
      + ' – K/Z son "MTM yenile"ye göre (TL); burada değerleme yapılmaz.', 'bugun-trades-mtm'));
    if (!t.count) {
      b.appendChild(none('Açık işlem yok (Kişisel ve Masa).', 'bugun-trades-none'));
      this.setCount(c, 0);
      return;
    }
    const near = t.near || [];
    if (near.length) {
      b.appendChild(h('div', { class: 'bugun-sub' }, 'Hedefe / stopa yakın'));
      const ul = h('ul', { class: 'bugun-near', id: 'bugun-trades-near' });
      for (const r of near) {
        const lv = r.levels;
        const stop = lv.near === 'stop';
        const dist = stop ? lv.to_stop : lv.to_target;
        ul.appendChild(h('li', { class: stop ? 'neg' : 'pos' }, h('b', null, stop ? 'Stopa yakın' : 'Hedefe yakın'), ' · ' + r.text
          + (isNum(dist) ? ' · ' + lvl(Math.abs(dist)) + (lv.unit ? ' ' + lv.unit : '') + ' kaldı' : '')
          + (isNum(stop ? lv.stop : lv.target) ? ' (' + (stop ? 'stop ' : 'hedef ') + lvl(stop ? lv.stop : lv.target) + ')' : '')));
      }
      b.appendChild(ul);
    }
    const table = h('table', { class: 'plain bugun', id: 'bugun-trades-table' });
    table.appendChild(h('tr', null, h('th', { class: 'l' }, 'Liste'), h('th', { class: 'l' }, 'İşlem'), h('th', null, 'Günlük K/Z'),
      h('th', null, 'Toplam K/Z'), t.levels ? h('th', { class: 'l' }, 'Hedef / stop') : null));
    for (const r of t.rows) {
      const lv = r.levels;
      const lvText = lv ? (isNum(lv.to_target) ? 'hedefe ' + lvl(Math.abs(lv.to_target)) : '') + (isNum(lv.to_target) && isNum(lv.to_stop) ? ' · ' : '')
        + (isNum(lv.to_stop) ? 'stopa ' + lvl(Math.abs(lv.to_stop)) : '') + (lv.unit ? ' ' + lv.unit : '') : '';
      const tip = r.why || (isNum(r.day_usd) ? 'USD: günlük ' + sgn(r.day_usd, 0) + ' · toplam ' + sgn(r.total_usd, 0) : '');
      table.appendChild(h('tr', { 'data-trade': String(r.id), class: lv && lv.near ? 'near-' + lv.near : null },
        td(r.scope === 'personal' ? 'Kişisel' : 'Masa' + (r.who ? ' · ' + r.who : ''), 'l muted'), td(r.text, 'l wrap', r.product),
        td(sgn(r.day), cls(r.day), tip || null), td(sgn(r.total), cls(r.total), tip || null),
        t.levels ? td(lvText, 'l' + (lv && lv.near ? (lv.near === 'stop' ? ' neg' : ' pos') : ' muted')) : null));
    }
    const sum = (k) => [tabs.personal, tabs.desk].reduce((a, x) => (x && isNum(x[k].try) ? (a === null ? 0 : a) + x[k].try : a), null);
    const miss = [tabs.personal, tabs.desk].reduce((a, x) => a + (x ? x.day.missing : 0), 0);
    table.appendChild(h('tr', { class: 'sum' }, td('Toplam', 'l'), td(t.count + ' açık işlem' + (miss ? ' · ' + miss + ' tanesinin K/Z\'si bilinmiyor' : ''), 'l muted'),
      td(sgn(sum('day')), cls(sum('day'))), td(sgn(sum('total')), cls(sum('total'))), t.levels ? td('') : null));
    b.appendChild(table);
    if (t.more) b.appendChild(note('ve ' + t.more + ' işlem daha: Trades sayfasında.'));
    this.setCount(c, near.length, true);
  }

  /** The quant's new lines (B19: two short lines each - the trade, then its levels and money - all of it on screen). */
  paintQuant(c, q) {
    const b = c.body;
    if (!q.ready) { b.appendChild(none(q.why || 'Quant sonucu henüz yok.', 'bugun-quant-none')); return; }
    const since = isoToTr(q.since.slice(0, 10)) + ' ' + q.since.slice(11);
    b.appendChild(note('Önceki kapanıştan (' + since + ') beri giriş eşiğini geçen ve yönü dönen ("YENİ") satırlar, beklenen kâra göre'
      + (q.at ? ' · quant ' + String(q.at).slice(11, 16) : '') + '.'));
    if (!q.count) {
      b.appendChild(none('Önceki kapanıştan beri yeni AL / SAT satırı yok.', 'bugun-quant-none'));
      this.setCount(c, 0);
      return;
    }
    const list = h('div', { class: 'bugun-qlist', id: 'bugun-quant-table' });
    for (const x of q.lines) {
      const line = h('div', { class: 'bugun-q go' + (x.listed ? '' : ' soft'), 'data-sid': x.sid, role: 'button', tabindex: '0',
        title: (x.model ? x.model + ' · ' : '') + (x.asset || '') + (x.gated ? ' · düşük güven: ' + x.gated : '')
          + (x.listed ? '' : ' · listeden çıktı (|z| geri döndü); kayıtta açık') + (x.exp_text ? '\n' + x.exp_text : '') + '\nTıklayınca sinyalin sayfası' },
      h('div', { class: 'q1' }, h('span', { class: 'qside ' + sideClass(x.side) }, x.side), h('span', { class: 'qtrade' }, x.trade),
        h('span', { class: 'muted qmeta' }, [x.size, x.time + (x.new ? ' · YENİ' : '')].filter(Boolean).join(' · '))),
      // (in the traded instrument's own level - an FX line's forward, the FRA / PPK line's FRA rate -; a model's gap beside it)
      h('div', { class: 'q2' }, h('span', { class: 'qlv' }, levelsLine(x)),
        isNum(x.exp_try) ? h('b', { class: 'qexp ' + cls(x.exp_try) }, ' · ' + sgn(x.exp_try, 0) + ' TL') : null,
        h('span', { class: 'muted' }, (x.unit ? ' · ' + x.unit : '') + (x.note ? ' · ' + x.note : ''))));
      const go = () => { window.location.hash = '#/' + (x.page || 'quant'); };
      line.addEventListener('click', go);
      line.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
      list.appendChild(line);
    }
    b.appendChild(list);
    if (q.more) b.appendChild(note('ve ' + q.more + ' satır daha: Sinyaller sayfasında.'));
    this.setCount(c, q.count, true);
  }

  paintDibs(c, x) {
    const b = c.body;
    const thr = isNum(x.threshold) ? ' (eşik ' + num(x.threshold, 1) + ' bp)' : '';
    b.appendChild(note((x.compared ? 'OIS / FX sinyali: masanın ' + isoToTr(x.prev_day) + ' kapanış kaydına göre'
      : 'OIS / FX sinyallerinde dünle kıyas yok: masanın kapanış kaydı henüz yok' + (x.first_record ? ' (ilki ' + x.first_record + '\'da alınır)' : '')
        + ' – bugünkü durum')
      + ' · sıfır kupon eğrisi: ' + (x.z_prev_day ? isoToTr(x.z_prev_day) + ' kapanışına göre' : (x.zero_why || 'dünle kıyas yok')) + thr + '.', 'bugun-dibs-note'));
    const rows = (x.turned || []).concat(x.now || []);
    if (!rows.length) {
      b.appendChild(none(x.compared || x.z_prev_day ? 'Önceki kapanışa göre sinyali dönen kâğıt yok.' : 'Şu an sinyal veren kâğıt yok.', 'bugun-dibs-none'));
      this.setCount(c, 0);
      return;
    }
    const table = h('table', { class: 'plain bugun', id: 'bugun-dibs-table' });
    table.appendChild(h('tr', null, h('th', { class: 'l' }, 'Kâğıt'), h('th', { class: 'l' }, 'OIS ASW'), h('th', { class: 'l' }, 'FX swap ASW'),
      h('th', { class: 'l' }, 'Sıfır kupon'), h('th', { class: 'l' }, '')));
    for (const r of rows) {
      table.appendChild(h('tr', { 'data-isin': r.isin, class: r.turned.length ? 'turned' : null },
        td(r.label, 'l bondlink', r.isin + ' · tıklayınca kâğıt kartı'), td(sigText(r.ois), 'l ' + sigClass(r.ois)),
        td(sigText(r.fx), 'l ' + sigClass(r.fx)), td(sigText(r.z), 'l ' + sigClass(r.z)), td(r.turned.length ? 'döndü' : '', 'l muted')));
    }
    b.appendChild(table);
    bondCardLinks(this.ctx, table);
    this.setCount(c, (x.turned || []).length, true);
  }

  paintChat(c, x) {
    const b = c.body;
    if (!x.count) {
      b.appendChild(none('Bugün chat\'te olup Günlük İşlemler\'de olmayan işlem yok.', 'bugun-chat-none'));
      this.setCount(c, 0);
      return;
    }
    b.appendChild(note('Masanın (Biz) bugün chat\'te yaptığı, Günlük İşlemler\'de bulunmayan işlemler: girin ya da listede eşleştirin / yok sayın.'));
    const table = h('table', { class: 'plain bugun', id: 'bugun-chat-table' });
    table.appendChild(h('tr', null, h('th', { class: 'l' }, 'Saat'), h('th', { class: 'l' }, 'Kimden'), h('th', { class: 'l' }, 'İşlem'),
      h('th', { class: 'l' }, 'Chat satırı')));
    for (const it of x.items) {
      table.appendChild(h('tr', { 'data-line': String(it.id) }, td(it.time, 'l muted'), td(it.source || it.sender || '', 'l'),
        td(chatWhat(it.q), 'l'), td(it.raw, 'l wrap muted')));
    }
    b.appendChild(table);
    if (x.more) b.appendChild(note('ve ' + x.more + ' satır daha: listede.'));
    this.setCount(c, x.count, true);
  }

  paintAgenda(c, a, d) {
    const b = c.body;
    const m = a.meetings || {};
    const meet = (key, name) => {
      const x = m[key];
      if (!x || !x.known) return null;
      if (x.today) return h('div', { class: 'bugun-line warn', id: 'bugun-agenda-' + key }, h('b', null, 'Bugün ' + name + ' kararı'));
      return h('div', { class: 'bugun-line', id: 'bugun-agenda-' + key }, 'Sıradaki ' + name + ': ',
        x.next ? h('b', null, isoToTr(x.next)) : 'takvimde yok', x.next && isNum(x.days) ? ' (' + (x.days === 1 ? 'yarın' : x.days + ' gün') + ')' : '');
    };
    const lines = [meet('ppk', 'PPK'), meet('fomc', 'FOMC')].filter(Boolean);
    for (const hol of a.holidays || []) {
      lines.push(h('div', { class: 'bugun-line warn' }, h('b', null, (hol.when === 'today' ? 'Bugün' : isoToTr(hol.day)) + ' '
        + (hol.ccy === 'USD' ? 'ABD' : 'TRY') + ' tatili'), hol.name ? ': ' + hol.name : '',
      hol.ccy === 'USD' ? ' – USD valörleri kayar' : ''));
    }
    if (a.calendar_error) lines.push(h('div', { class: 'err' }, 'Toplantı takvimi okunamadı: ' + a.calendar_error));
    for (const el of lines) b.appendChild(el);
    const item = (it, late) => h('li', { class: (it.done ? 'done' : '') + (late ? ' late' : '') },
      h('span', { class: 'muted' }, (late ? isoToTr(it.day) + ' ' : '') + (it.time || 'gün içi')), ' ',
      it.deadline ? h('b', { class: 'bugun-dl' }, 'deadline') : null, it.deadline ? ' ' : null, it.text,
      h('span', { class: 'muted' }, ' · ' + (it.shared ? 'Masa' : 'Kişisel') + (it.repeat ? ' · ' + it.repeat : '') + (it.done ? ' · tamam' : '')));
    if ((a.late || []).length) {
      b.appendChild(h('div', { class: 'bugun-sub neg' }, 'Geciken deadline'));
      b.appendChild(h('ul', { class: 'bugun-items', id: 'bugun-agenda-late' }, ...a.late.map((it) => item(it, true))));
    }
    if ((a.items || []).length) {
      b.appendChild(h('div', { class: 'bugun-sub' }, 'Bugün'));
      b.appendChild(h('ul', { class: 'bugun-items', id: 'bugun-agenda-items' }, ...a.items.map((it) => item(it, false))));
    } else {
      b.appendChild(none('Bugün için ajandada iş yok.', 'bugun-agenda-none'));
    }
    const open = (a.items || []).filter((it) => !it.done).length + (a.late || []).length;
    this.setCount(c, open, (a.late || []).length > 0);
  }
}

function errToBody(c, err) {
  c.body.appendChild(h('div', { class: 'err' }, 'Çizilemedi: ' + err.message));
}
