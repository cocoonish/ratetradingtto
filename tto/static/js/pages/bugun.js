// Bugün: the morning screen - what wants attention, on one page (/api/bugun, tto/bugun.py): the RET, the open trades
// (their P&L as of the last "MTM yenile": nothing is valued here), the quant's new AL / SAT lines, the DİBS bonds whose
// signal turned, the chat's trades not entered, today's agenda and meetings.  Every block leads to where its thing is
// handled and says plainly when there is nothing.  Read again with the market's generations (at most every 20 s), when
// the agenda or the trades change (the live stream's counters) and with "Yenile"; "Açılış sayfası yap" makes it the page
// the dashboard opens on.
import { api } from '../api.js';
import { h, clear, toast, errorToast } from '../ui.js';
import { num, isoToTr } from '../format.js';
import { landing, setLanding } from '../layout.js';
import { level } from './broker.js';

const EVERY = 20000;               // ms: the market's generations read the page again at most this often

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
const note = (text, id) => h('div', { class: 'muted bugun-note', id: id || null }, text);
const td = (text, c, title) => h('td', { class: c || null, title: title || null }, text);

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
    this.grid = h('div', { class: 'bugun-grid', id: 'bugun' });
    this.host.appendChild(this.grid);
    const card = (key, title, link, tip, go) => {
      const count = h('span', { class: 'bugun-count hidden', id: 'bugun-' + key + '-count' });
      const btn = h('button', { class: 'btn sm', type: 'button', id: 'bugun-' + key + '-go', title: tip }, link + ' →');
      btn.addEventListener('click', go);
      const body = h('div', { class: 'bugun-body', id: 'bugun-' + key + '-body' });
      const el = h('section', { class: 'panel bugun-card', id: 'bugun-' + key }, h('header', null, h('h2', null, title), count, btn), body);
      this.grid.appendChild(el);
      this.cards[key] = { el, body, count };
    };
    const hash = (x) => () => { window.location.hash = '#/' + x; };
    card('ret', 'RET', 'RET penceresi', 'RET faizleri penceresi: yüklenmediyse elle giriş, güncelleme varsa adil değer sekmesinde açılır',
      () => this.openRet());
    card('trades', 'Trades · açık işlemler', 'Trades', 'Trades sayfası: MTM yenile, işlemler, kapanış', hash('trades'));
    card('quant', 'Quant · yeni AL / SAT', 'Sinyaller', 'Quant › Sinyaller: bütün liste, kartlar, kayıt', hash('quant'));
    card('dibs', 'DİBS · sinyali dönen kâğıtlar', 'DİBS RV · Genel', 'DİBS RV · Genel: trading listesinin kâğıtları OIS ASW, FX swap ASW ve sıfır kupon eğrisine göre',
      hash('dibs-genel'));
    card('chat', 'Girilmemiş işlemler', 'Chat ↔ Günlük İşlemler', 'Masanın chat\'teki işlemleri Günlük İşlemler\'in yanında: eşleştir, yok say, gir',
      () => this.ctx.openRecon().catch(errorToast));
    card('agenda', 'Ajanda · takvim', 'Ajanda', 'Ajanda: bugünün işleri, deadline\'lar, tekrarlayan işler', hash('agenda'));
  }

  openRet(tab) {
    const t = tab || (this.data && this.data.ret && this.data.ret.tab) || null;
    this.ctx.openRet(t ? { tab: t } : undefined);
  }

  paint() {
    const d = this.data;
    if (!d) return;
    this.stamp.textContent = isoToTr(d.today) + ' · ' + d.time + ' itibarıyla';
    this.paintLanding();
    for (const [key, fn] of [['ret', this.paintRet], ['trades', this.paintTrades], ['quant', this.paintQuant], ['dibs', this.paintDibs],
      ['chat', this.paintChat], ['agenda', this.paintAgenda]]) {
      const c = this.cards[key];
      const x = d[key] || {};
      clear(c.body);
      c.count.classList.add('hidden');
      c.el.classList.remove('bugun-attn');
      if (x.error) { c.body.appendChild(h('div', { class: 'err' }, 'Okunamadı: ' + x.error.replace(/^okunamadı: /, ''))); continue; }
      if (x.available === false) { c.body.appendChild(none('Bu dashboard\'da yok (çalışma kitabı yüklü değil).')); continue; }
      try { fn.call(this, c, x, d); } catch (err) { c.body.appendChild(h('div', { class: 'err' }, 'Çizilemedi: ' + err.message)); }
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
    const table = h('table', { class: 'plain bugun', id: 'bugun-quant-table' });
    table.appendChild(h('tr', null, h('th', { class: 'l' }, 'Saat'), h('th', { class: 'l' }, 'Yön'), h('th', { class: 'l' }, 'İşlem'),
      h('th', { class: 'l' }, 'Büyüklük'), h('th', null, 'Giriş / hedef / stop'), h('th', null, 'Ödül / risk'), h('th', null, 'Beklenen')));
    for (const x of q.lines) {
      const p = (v) => (isNum(v) ? num(v, x.digits) : '—');
      const tr = h('tr', { class: 'go' + (x.listed ? '' : ' soft'), 'data-sid': x.sid,
        title: (x.model ? x.model + ' · ' : '') + (x.asset || '') + (x.gated ? ' · düşük güven: ' + x.gated : '')
          + (x.listed ? '' : ' · listeden çıktı (|z| geri döndü); kayıtta açık') + ' · tıklayınca sinyalin sayfası' },
      td(x.time + (x.new ? ' · YENİ' : ''), 'l muted'), td(x.side, 'l ' + (x.up ? 'buy' : 'sell')), td(x.trade, 'l wrap'),
      td(x.size || '', 'l muted'), td(p(x.entry) + ' / ' + p(x.target) + ' / ' + p(x.stop) + (x.unit ? ' ' + x.unit : '')),
      td(isNum(x.rr) ? num(x.rr, 2) : '—'), td(isNum(x.exp_try) ? sgn(x.exp_try, 0) + ' TL' : (x.exp_text || '—'), isNum(x.exp_try) ? cls(x.exp_try) : 'muted', x.exp_text || null));
      tr.addEventListener('click', () => { window.location.hash = '#/' + (x.page || 'quant'); });
      table.appendChild(tr);
    }
    b.appendChild(table);
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
        td(r.label, 'l', r.isin), td(sigText(r.ois), 'l ' + sigClass(r.ois)), td(sigText(r.fx), 'l ' + sigClass(r.fx)),
        td(sigText(r.z), 'l ' + sigClass(r.z)), td(r.turned.length ? 'döndü' : 'dünle kıyas yok', 'l muted')));
    }
    b.appendChild(table);
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
