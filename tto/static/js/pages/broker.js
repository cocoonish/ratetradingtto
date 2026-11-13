// Broker Chat: what the brokers write about TRY rates, pasted or typed as it stands.  Every line is read
// (outright / spread / fly / FRA, one side or two, a level without its big figure, trades, refs ...), kept with
// its time and sender, and shown twice: as a board of where every instrument stands - next to the dashboard's
// own curve - and as the chat in the order it was said.  Shared by every user, like the blotter.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, debounce } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { num, isoToTr } from '../format.js';

const KIND = { outright: 'Outright', spread: 'Spread', fly: 'Fly', fra: 'FRA', fwd: 'Forward' };
const EVENT = { quote: 'Kota', trade: 'İşlem', ref: 'Ref', interest: 'İlgi', level: 'Seviye', note: 'Not', text: 'Metin' };
const FLAG = {
  abbr: ['tamamlandı', '', 'Büyük rakam yazılmamış ("90 bid"): kotanın öbür tarafından, bu enstrümanın son seviyesinden ya da eğriden tamamlandı'],
  ambiguous: ['belirsiz', 'warn', 'İki türlü okunabilir ("36": 35,36 mı 36,00 mı?) – yakın olan alındı; yanlışsa seviyeyi tam yazın'],
  'no-ref': ['büyük rakam yok', 'warn', 'Seviyeyi tamamlayacak bir referans yok (bu enstrüman için ne önceki kota ne eğri) – yazıldığı gibi alındı'],
  'side?': ['taraf?', 'warn', 'Eğik çizgi ile kelime uyuşmuyor ("12/ offer") – eğik çizgiye uyuldu'],
  crossed: ['bid > ask', 'warn', 'Bid ask\'ten yüksek okundu'],
  standing: ['kotadan', '', 'Mesajda fiyat yok ("taken", "given"): o an duran offer / bid seviyesi alındı'],
};
const KNOWN = 'Bu satır zaten kayıtlı – yeniden eklenmez';
const EXAMPLES = [
  ['12:15:38 18m ois 35.03/35.23', 'outright, iki taraf'],
  ['12:10:07 18m ois /35.23 offer', 'yalnızca offer (bid yok)'],
  ['6m OIS 90 bid', 'büyük rakam tamamlanır: 35,90'],
  ['18m ois 10/14', '35,10 / 35,14'],
  ['10:29:57 1y5y ois -64/-60', 'spread (5Y − 1Y, bp) – "v" yazılmasa da FRA değil spread'],
  ['1v5y ois -62 bid', 'spread, "v" ile'],
  ['12:18:04 2y3y4y ois 12/ bid', 'fly (2×3Y − 2Y − 4Y, bp)'],
  ['12:11:55 9x12m ois fra 33.80/34.10', 'FRA ("9x12" ya da "fra" kelimesi)'],
  ['18m ois taken at 14', 'işlem: offer 35,14\'ten alındı'],
  ['ref 18m ois offer', 'offer geri çekildi'],
  ['2yr ois 35.46, oco with 18m 35.14 offer', 'iki offer, biri öbürünü iptal eder'],
  ['1yr x 38.60/80', 'cross-currency ("x")'],
];

/** A level as it is quoted: per cent with at least two decimals, basis points with as many as were typed. */
export function level(v, unit) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  let d = unit === 'pct' ? 2 : 0;
  const most = unit === 'pct' ? 4 : 2;
  while (d < most && Math.abs(v * 10 ** d - Math.round(v * 10 ** d)) > 1e-7) d += 1;
  return num(v, d, false);
}

function fold(text) {
  return String(text || '').toLocaleLowerCase('tr').replace(/ı/g, 'i');
}

function isoDay(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

/** What happened, in the desk's words. */
export function eventText(q) {
  const side = q.side === 'bid' ? 'bid' : (q.side === 'ask' ? 'offer' : '');
  if (q.event === 'trade') return 'İşlem' + (q.side === 'ask' ? ' · offer alındı' : (q.side === 'bid' ? ' · bid\'e verildi' : ''));
  if (q.event === 'ref') return 'Ref' + (side ? ' · ' + side : '');
  if (q.event === 'interest') return 'İlgi' + (side ? ' · ' + side : '');
  return EVENT[q.event] || q.event || '';
}

function kindText(q) {
  return q.ok === false ? '' : (KIND[q.kind] || q.kind || '') + (q.unit === 'bp' ? ' (bp)' : '');
}

export class BrokerPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.date = null;
    this.to = null;
    this.data = null;
    this.grids = {};
    this.same = {};
    this.draft = '';
    this.product = 'all';         // board: all / OIS / XCCY
    this.only = null;             // log: one instrument ({key, label}) ...
    this.find = '';               // ... and / or a search text
    this.quotesOnly = false;
    this.seq = 0;
    this.parsed = null;
    this.preview = debounce(() => this.doPreview(), 240);
  }

  query() {
    if (!this.date) return null;
    return this.to && this.to !== this.date ? { date: this.date, to: this.to } : { date: this.date };
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const data = await api.get('/api/broker', this.query());
    if (this.dead) return;
    this.data = data;
    this.date = data.date;
    this.to = data.ranged ? data.to : null;
    this.build();
    this.fill();
    if (this.draft.trim()) this.doPreview();
  }

  async refresh() {
    const data = await api.get('/api/broker', this.query());
    if (this.dead) return;
    this.data = data;
    this.fill();
  }

  destroy() {
    this.dead = true;
    this.preview.cancel();
    if (this.text) this.draft = this.text.value;
  }

  /** Show one day (``to`` empty) or every day of a period. */
  show(from, to) {
    if (!from) return;
    if (to && to < from) { const x = from; from = to; to = x; }
    if (this.text) this.draft = this.text.value;
    this.date = from;
    this.to = to && to !== from ? to : null;
    this.load().catch(errorToast);
  }

  // ------------------------------------------------------------------ layout
  build() {
    clear(this.host);
    this.grids = {};
    this.same = {};
    const d = this.data;
    this.dateSel = h('select', { class: 'inp', id: 'broker-day' });
    this.dateSel.addEventListener('change', () => { if (this.dateSel.value) this.show(this.dateSel.value, null); });
    this.fromInp = h('input', { type: 'date', class: 'inp', id: 'broker-from', title: 'Başlangıç günü' });
    this.toInp = h('input', { type: 'date', class: 'inp', id: 'broker-to', title: 'Bitiş günü' });
    const go = h('button', { class: 'btn sm primary', type: 'button', id: 'broker-range' }, 'Göster');
    go.addEventListener('click', () => {
      if (!this.fromInp.value || !this.toInp.value) { toast('Aralığın iki tarihini de seçin', 'err'); return; }
      this.show(this.fromInp.value, this.toInp.value);
    });
    for (const el of [this.fromInp, this.toInp]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
    const preset = (label, title, fn) => {
      const b = h('button', { class: 'btn sm', type: 'button', title }, label);
      b.addEventListener('click', () => { const [a, z] = fn(new Date()); this.show(isoDay(a), isoDay(z)); });
      return b;
    };
    const range = h('span', { class: 'rangebox' }, h('span', { class: 'muted' }, 'Aralık'), this.fromInp, h('span', { class: 'muted' }, '–'), this.toInp, go,
      preset('Bu hafta', 'Pazartesiden bugüne', (t) => { const a = new Date(t); a.setDate(t.getDate() - ((t.getDay() + 6) % 7)); return [a, t]; }),
      preset('Son 30 gün', 'Otuz gün öncesinden bugüne', (t) => { const a = new Date(t); a.setDate(t.getDate() - 30); return [a, t]; }));
    this.todayBtn = h('button', { class: 'btn sm', type: 'button', id: 'broker-today', title: 'Bugünün chat\'ine dön' }, 'Bugün');
    this.todayBtn.addEventListener('click', () => this.show(this.data.today, null));
    this.exportBtn = h('button', { class: 'btn sm', type: 'button', id: 'broker-export',
      title: 'Görüntülenen günün / aralığın tahtasını ve bütün kayıtlarını Excel dosyası olarak indir (BrokerChat_yyyy.aa.gg.xlsx)' }, 'Excel (.xlsx)');
    this.exportBtn.addEventListener('click', async () => {
      this.exportBtn.disabled = true;
      try {
        const res = await api.download('/api/broker/export', { date: this.date || undefined, to: this.to || undefined }, 'BrokerChat.xlsx');
        toast(res.name + ' indirildi', 'ok', 3200);
      } catch (err) { errorToast(err); } finally { this.exportBtn.disabled = false; }
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'Gün'), this.dateSel, this.todayBtn, range, this.exportBtn,
      h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Kaydedilen kotalar tüm kullanıcılarda anında görünür')));
    this.dayNote = h('div', { class: 'banner hidden' });
    this.host.appendChild(this.dayNote);

    // ---- entry: paste or type, see how it is read, keep it
    this.text = h('textarea', { id: 'broker-text', class: 'inp chatbox', rows: '9', spellcheck: 'false', autocomplete: 'off',
      placeholder: 'Chat\'i buraya yapıştırın ya da yazın – her satır bir mesaj:\n\n12:15:38 18m ois 35.03/35.23\n12:10:07 18m ois /35.23 offer\n'
        + '10:29:57 1y5y ois -64/-60\n12:18:04 2y3y4y ois 12/ bid\n12:11:55 9x12m ois fra 33.80/34.10\n6m OIS 90 bid' });
    this.text.value = this.draft;
    this.text.addEventListener('input', () => { this.draft = this.text.value; this.preview(); });
    this.text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.save(); } });
    this.source = h('input', { type: 'text', id: 'broker-source', class: 'inp', maxlength: '40', placeholder: 'örn. Tullett', list: 'broker-sources',
      autocomplete: 'off', title: 'Chat\'in kimden / hangi kurumdan olduğu – her satırla birlikte saklanır' });
    try { this.source.value = localStorage.getItem('tto.broker.source') || ''; } catch (e) { /* ignore */ }
    this.sources = h('datalist', { id: 'broker-sources' });
    this.entryDate = h('input', { type: 'date', id: 'broker-date', class: 'inp',
      title: 'Kotaların günü. Chat\'in içinde tarih satırı varsa o geçerlidir.' });
    this.entryDate.value = d.ranged ? d.today : d.date;
    this.entryDate.addEventListener('change', () => this.preview());
    this.keepTexts = h('input', { type: 'checkbox', id: 'broker-texts' });
    let keep = true;
    try { keep = localStorage.getItem('tto.broker.texts') !== '0'; } catch (e) { /* ignore */ }
    this.keepTexts.checked = keep;
    this.keepTexts.addEventListener('change', () => {
      try { localStorage.setItem('tto.broker.texts', this.keepTexts.checked ? '1' : '0'); } catch (e) { /* ignore */ }
      this.showPreview();
    });
    this.previewBox = h('div', { class: 'chatpreview', id: 'broker-preview' });
    this.summary = h('span', { class: 'muted', id: 'broker-summary' });
    this.saveBtn = h('button', { class: 'btn primary', type: 'button', id: 'broker-save', title: 'Kaydet (Ctrl+Enter)' }, 'Kaydet');
    this.saveBtn.addEventListener('click', () => this.save());
    const wipe = h('button', { class: 'btn', type: 'button', id: 'broker-clear' }, 'Temizle');
    wipe.addEventListener('click', () => { this.text.value = ''; this.draft = ''; this.parsed = null; this.showPreview(); this.text.focus(); });
    const help = h('details', { class: 'chathelp' }, h('summary', null, 'Nasıl okunur?'),
      h('table', { class: 'plain' }, EXAMPLES.map(([line, what]) => h('tr', null, h('td', { class: 'l mono' }, line), h('td', { class: 'l' }, what)))),
      h('div', { class: 'muted pad0' }, 'Saat satırın başında, sonunda ya da (telefondaki gibi) alt satırda olabilir; saat yoksa girildiği an yazılır. '
        + 'İsim satırı ya da "İSİM: mesaj" göndereni belirler. Aynı chat ikinci kez yapıştırılırsa yalnızca yeni satırlar eklenir.'));
    const entry = h('div', { class: 'card entry' }, h('header', null, h('h2', null, 'Chat\'ten ekle')),
      h('div', { class: 'pad form' }, this.text,
        h('div', { class: 'chatrow' },
          h('div', { class: 'field' }, h('label', { for: 'broker-source' }, 'Kaynak'), this.source, this.sources),
          h('div', { class: 'field' }, h('label', { for: 'broker-date' }, 'Tarih'), this.entryDate),
          h('label', { class: 'check', title: 'Kapalıyken yalnızca enstrüman içeren satırlar saklanır' }, this.keepTexts, ' Metin satırlarını da sakla')),
        this.previewBox,
        h('div', { class: 'chatrow actions' }, this.summary, h('span', { class: 'grow' }), wipe, this.saveBtn),
        help));

    // ---- board: where every instrument stands
    const seg = h('div', { class: 'seg', id: 'broker-product' });
    for (const [v, label] of [['all', 'Tümü'], ['OIS', 'OIS'], ['XCCY', 'XCCY']]) {
      const b = h('button', { type: 'button' }, label);
      b.dataset.v = v;
      b.addEventListener('click', () => { this.product = v; this.fill(); });
      seg.appendChild(b);
    }
    this.productSeg = seg;
    this.board = this.panel('board', 'Tahta · son durum', [seg],
      'Bid / ask: en son söylenen kota (geri çekilen taraf boş). Model: dashboard\'un kendi TRY OIS eğrisi (sizin senaryonuzla); '
      + 'farklar baz puan – bid model\'in üstünde ya da ask model\'in altındaysa vurgulanır.');
    // ---- log: the chat in the order it was said
    this.findInp = h('input', { type: 'search', class: 'inp', id: 'broker-find', placeholder: 'Ara: 18m, spread, isim…', autocomplete: 'off' });
    this.findInp.value = this.find;
    this.findInp.addEventListener('input', () => { this.find = this.findInp.value; this.fillLog(); });
    this.onlyBtn = h('button', { class: 'btn sm on hidden', type: 'button', id: 'broker-only', title: 'Enstrüman süzgecini kaldır' });
    this.onlyBtn.addEventListener('click', () => { this.only = null; this.fillLog(); });
    this.quotesBox = h('input', { type: 'checkbox', id: 'broker-quotes' });
    this.quotesBox.checked = this.quotesOnly;
    this.quotesBox.addEventListener('change', () => { this.quotesOnly = this.quotesBox.checked; this.fillLog(); });
    this.log = this.panel('log', 'Kayıt · söylendiği sırayla', [this.onlyBtn, this.findInp,
      h('label', { class: 'check' }, this.quotesBox, ' Yalnızca kotalar')]);
    // entry and board side by side, the chat itself across the page below them
    this.host.appendChild(h('div', { class: 'broker' }, h('div', { class: 'entrycol' }, entry), h('div', { class: 'boardcol' }, this.board.el),
      h('div', { class: 'logcol' }, this.log.el)));
    this.showPreview();
  }

  panel(id, title, extra, hint) {
    const body = h('div', { class: 'body' });
    const count = h('span', { class: 'muted' });
    const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    cp.addEventListener('click', () => { if (this.grids[id]) copyGrid(this.grids[id]); });
    const head = h('header', null, h('h2', { title: hint || '' }, title), count, h('span', { class: 'grow' }), extra, h('div', { class: 'tools' }, cp));
    const el = h('section', { class: 'panel wide', id: 'broker-' + id + '-panel' }, head, body);
    return { el, body, count };
  }

  /**
   * ``same``: a text that stays the same as long as the table lists the same things.  Then only numbers that
   * follow the market (the model, the differences) can have moved: they are patched in place, and a selection
   * or a tooltip being read is left alone.  Anything else rebuilds the table (its row buttons belong to rows).
   */
  setGrid(id, sec, header, rows, countText, emptyText, same) {
    sec.count.textContent = countText || '';
    if (!rows.length) {
      clear(sec.body);
      this.grids[id] = null;
      this.same[id] = null;
      sec.body.appendChild(h('div', { class: 'empty' }, emptyText));
      return;
    }
    const data = plainData(header, rows);
    if (this.grids[id] && this.same[id] === same) {
      this.grids[id].update(data, true);
    } else if (this.grids[id]) {
      this.grids[id].replace(data);
    } else {
      clear(sec.body);
      this.grids[id] = new Grid({ data, editable: false });
      sec.body.appendChild(this.grids[id].el);
    }
    this.same[id] = same;
  }

  // ------------------------------------------------------------------ what is kept
  fill() {
    const d = this.data;
    clear(this.dateSel);
    const seen = new Set();
    const add = (iso, label) => { if (!seen.has(iso)) { seen.add(iso); this.dateSel.appendChild(h('option', { value: iso }, label)); } };
    if (d.ranged) this.dateSel.appendChild(h('option', { value: '' }, 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to)));
    add(d.today, isoToTr(d.today) + ' (bugün)');
    for (const x of d.dates) add(x.date, isoToTr(x.date) + ' · ' + x.count + ' satır');
    if (!d.ranged) add(d.date, isoToTr(d.date));
    this.dateSel.value = d.ranged ? '' : d.date;
    this.fromInp.value = d.date;
    this.toInp.value = d.to || d.date;
    this.todayBtn.classList.toggle('hidden', d.is_today);
    this.dayNote.textContent = d.is_today ? '' : (d.ranged
      ? 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to) + ' · ' + d.rows.length + ' satır. Tahta, aralığın sonundaki durumu gösterir.'
      : 'Geçmiş gün: ' + isoToTr(d.date) + '. Buraya eklenen chat bu güne yazılır (ya da "Tarih" kutusundaki güne).');
    this.dayNote.classList.toggle('hidden', d.is_today);
    clear(this.sources);
    for (const s of new Set(d.rows.map((q) => q.source).filter(Boolean))) this.sources.appendChild(h('option', { value: s }));

    // ---- board
    for (const b of this.productSeg.children) b.classList.toggle('on', b.dataset.v === this.product);
    const when = (stamp) => {
      if (!stamp) return '';
      const [day, time] = stamp.split(' ');
      return d.ranged ? isoToTr(day).slice(0, 5) + ' ' + (time || '') : (time || day);
    };
    const side = (v, unit, stamp, name) => (typeof v === 'number' ? { t: level(v, unit), v, k: 'n', tip: name + ': ' + when(stamp) } : { t: '', k: '', tip: stamp ? name + ' yok: ' + when(stamp) : '' });
    const diff = (v, through) => (typeof v === 'number' ? { t: (v > 0 ? '+' : '') + num(v, 1, false), v, k: 'n', cls: through ? 'thru' : '',
      tip: through ? 'Kota model seviyesinin öbür tarafında' : '' } : { t: '', k: '' });
    const board = d.board.filter((r) => this.product === 'all' || r.product === this.product);
    this.setGrid('board', this.board,
      ['Ürün', 'Enstrüman', 'Tür', 'Bid', 'Ask', 'Saat', 'Son işlem', 'Model', 'Bid − model (bp)', 'Ask − model (bp)', 'Son mesaj', ''],
      board.map((r) => [r.product, { t: r.label, k: 's', b: 1 }, kindText(r),
        side(r.bid, r.unit, r.bid_time, 'Bid'), side(r.ask, r.unit, r.ask_time, 'Ask'),
        when(r.time), typeof r.last === 'number' ? { t: level(r.last, r.unit), v: r.last, k: 'n', cls: r.last_side === 'ask' ? 'buy' : (r.last_side === 'bid' ? 'sell' : ''),
          tip: when(r.last_time) + (r.last_side === 'ask' ? ' · offer alındı' : (r.last_side === 'bid' ? ' · bid\'e verildi' : '')) } : { t: '', k: '' },
        typeof r.mid === 'number' ? { t: num(r.mid, r.unit === 'pct' ? 2 : 1, false), v: r.mid, k: 'n', cls: 'soft' } : { t: '', k: '' },
        diff(r.bid_diff, r.bid_diff > 0), diff(r.ask_diff, r.ask_diff < 0), { t: r.said || '', k: 's', cls: 'said short', tip: r.said || '' },
        { t: '', k: '', cls: 'act', act: { label: '≡', title: r.label + ' için söylenenlerin hepsini aşağıda göster', fn: () => this.showOnly(r) } }]),
      d.board.length ? board.length + ' enstrüman' : '', d.board.length ? 'Bu üründe kota yok' : 'Henüz kota yok – soldaki kutuya chat\'i yapıştırın',
      JSON.stringify([d.ranged, board.map((r) => [r.key, r.bid, r.ask, r.last, r.last_side, r.bid_time, r.ask_time, r.last_time, r.time, r.said,
        typeof r.mid === 'number'])]));
    this.fillLog();
  }

  showOnly(r) {
    this.only = { key: r.key, label: (r.product === 'OIS' ? '' : r.product + ' ') + r.label };
    this.fillLog();
    this.log.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  fillLog() {
    const d = this.data;
    const needle = fold(this.find).trim();
    this.onlyBtn.classList.toggle('hidden', !this.only);
    this.onlyBtn.textContent = this.only ? 'Yalnızca ' + this.only.label + ' ✕' : '';
    const rows = d.rows.filter((q) => {
      if (this.only && q.key !== this.only.key) return false;
      if (this.quotesOnly && !q.ok) return false;
      if (!needle) return true;
      return fold([q.raw, q.label, q.product, KIND[q.kind], q.sender, q.source, eventText(q), q.note].join(' ')).includes(needle);
    });
    const dayHead = d.ranged ? ['Tarih'] : [];
    const lv = (q, v) => (typeof v === 'number' ? { t: level(v, q.unit), v, k: 'n' } : { t: '', k: '' });
    const stamp = (q) => 'Giren: ' + (this.ctx.displayName(q.created_by) || '?') + (q.created_at ? ' · ' + q.created_at.replace('T', ' ').slice(0, 19) : '')
      + (q.timed === false ? '\nMesajda saat yoktu: girildiği an yazıldı' : '');
    this.setGrid('log', this.log,
      dayHead.concat(['Saat', 'Kimden', 'Mesaj', 'Enstrüman', 'Tür', 'Bid', 'Ask', 'İşlem / seviye', 'Olay', 'Model (girişte)', 'Not', '']),
      rows.map((q) => (d.ranged ? [{ t: isoToTr(q.date), k: 's' }] : []).concat([
        { t: q.time, k: 's', cls: q.timed === false ? 'soft' : '', tip: stamp(q) },
        [q.sender, q.source].filter(Boolean).join(' · '), { t: q.raw || '', k: 's', cls: 'said', tip: q.raw || '' },
        q.ok ? { t: (q.product === 'OIS' ? '' : q.product + ' ') + q.label, k: 's', b: 1 } : '', kindText(q),
        lv(q, q.bid), lv(q, q.ask), q.ok && typeof q.price === 'number' ? { t: level(q.price, q.unit), v: q.price, k: 'n',
          cls: q.event === 'trade' ? (q.side === 'ask' ? 'buy' : (q.side === 'bid' ? 'sell' : '')) : '' } : { t: '', k: '' },
        { t: eventText(q) + (q.oco ? ' · OCO' : '') + ((q.flags || []).some((f) => FLAG[f] && FLAG[f][1] === 'warn') ? ' ⚠' : ''), k: 's', cls: q.ok ? '' : 'soft',
          tip: (q.flags || []).map((f) => (FLAG[f] ? FLAG[f][0] + ': ' + FLAG[f][2] : f)).join('\n') },
        q.ok && typeof q.model === 'number' ? { t: num(q.model, q.unit === 'pct' ? 2 : 1, false), v: q.model, k: 'n', cls: 'soft',
          tip: 'Satır girildiği anda dashboard eğrisinin bu enstrüman için verdiği seviye' } : { t: '', k: '' },
        q.note || '',
        { t: '', k: '', cls: 'act', act: { label: '✕', title: 'Satırı sil', fn: () => this.remove(q) } }])),
      d.rows.length ? (rows.length === d.rows.length ? rows.length + ' satır' : rows.length + ' / ' + d.rows.length + ' satır') : '',
      d.rows.length ? 'Süzgece uyan satır yok' : (d.ranged ? 'Bu aralıkta kayıt yok' : 'Bu gün için kayıt yok'),
      JSON.stringify([d.ranged, rows.map((q) => q.id)]));
  }

  async remove(q) {
    const ok = await confirmDialog('Satırı sil', q.time + ' · ' + (q.raw || '') + ' silinsin mi? Silinen satır tüm kullanıcılardan kalkar.', 'Sil', true);
    if (!ok) return;
    try {
      await api.del('/api/broker/' + q.id);
      toast('Satır silindi', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ entry
  async doPreview() {
    const text = this.text.value;
    const seq = ++this.seq;
    if (!text.trim()) { this.parsed = null; this.showPreview(); return; }
    try {
      const res = await api.post('/api/broker/parse', { text, date: this.entryDate.value || null });
      if (this.dead || seq !== this.seq) return;
      this.parsed = res;
    } catch (err) {
      if (this.dead || seq !== this.seq) return;
      this.parsed = { error: err.message, rows: [] };
    }
    this.showPreview();
  }

  showPreview() {
    const p = this.parsed;
    clear(this.previewBox);
    this.summary.textContent = '';
    this.summary.className = 'muted';
    if (!p) { this.saveBtn.disabled = !this.text.value.trim(); return; }
    if (p.error) { this.previewBox.appendChild(h('div', { class: 'errtxt' }, p.error)); return; }
    const keep = this.keepTexts.checked;
    const rows = p.rows.filter((q) => q.ok || keep);
    const pill = (text, cls, title) => h('span', { class: 'pill ' + (cls || 'neu'), title: title || '' }, text);
    const table = h('table', { class: 'plain chat' }, h('tr', null, h('th', { class: 'l' }, 'Saat'), h('th', { class: 'l' }, 'Enstrüman'),
      h('th', null, 'Bid'), h('th', null, 'Ask'), h('th', { title: 'İşlem fiyatı ya da tarafı söylenmemiş seviye' }, 'Fiyat'), h('th', { class: 'l' }, 'Olay')));
    for (const q of rows) {
      const marks = [];
      // a completed big figure is marked on the numbers themselves; what may be wrong gets a label
      for (const f of q.flags || []) { const x = FLAG[f]; if (x && x[1] === 'warn') marks.push(pill(x[0], x[1], x[2])); }
      const short = (q.flags || []).find((f) => f === 'abbr' || f === 'ambiguous' || f === 'standing');
      const numCell = (v, cls) => h('td', { class: (cls || '') + (short && typeof v === 'number' ? ' abbr' : ''),
        title: short && typeof v === 'number' ? FLAG[short === 'standing' ? 'standing' : 'abbr'][2] : '' }, level(v, q.unit));
      if (q.oco) marks.push(pill('OCO', 'neu', 'Biri yapılırsa öbürü iptal'));
      const time = h('td', { class: 'l' + (q.timed ? '' : ' soft'), title: q.timed ? '' : 'Mesajda saat yok: kaydedildiği an yazılır' }, q.timed ? q.time : 'şimdi');
      if (!q.ok) {
        table.appendChild(h('tr', { class: 'txt' + (q.dup ? ' dup' : ''), title: q.dup ? KNOWN : '' }, time, h('td', { class: 'l said', colspan: '4', title: q.raw }, q.raw),
          h('td', { class: 'l what soft' }, 'Metin', marks)));
        continue;
      }
      const who = [q.sender, q.raw].filter(Boolean).join(': ');
      table.appendChild(h('tr', { class: q.dup ? 'dup' : '', title: q.dup ? KNOWN : who }, time,
        h('td', { class: 'l' }, h('b', null, (q.product === 'OIS' ? '' : q.product + ' ') + q.label),
          q.kind === 'outright' ? null : h('span', { class: 'kind' }, (KIND[q.kind] || q.kind).toLowerCase() + (q.unit === 'bp' ? ' · bp' : ''))),
        numCell(q.bid), numCell(q.ask), numCell(q.price, q.event === 'trade' ? (q.side === 'ask' ? 'buy' : (q.side === 'bid' ? 'sell' : '')) : ''),
        h('td', { class: 'l what' }, eventText(q) + (q.note ? ' · ' + q.note : ''), marks)));
    }
    if (rows.length) this.previewBox.appendChild(table);
    const fresh = rows.filter((q) => !q.dup);
    const quotes = fresh.filter((q) => q.ok).length;
    const parts = [quotes + ' kota'];
    if (fresh.length - quotes) parts.push((fresh.length - quotes) + ' metin satırı');
    if (rows.length - fresh.length) parts.push((rows.length - fresh.length) + ' satır zaten kayıtlı');
    const warn = rows.some((q) => (q.flags || []).some((f) => FLAG[f] && FLAG[f][1] === 'warn'));
    this.summary.textContent = rows.length ? parts.join(' · ') + (warn ? ' – işaretli satırlara bakın' : '') : 'Okunacak satır yok';
    if (warn) this.summary.className = 'warn-text';
    this.saveBtn.disabled = !fresh.length;
  }

  async save() {
    const text = this.text.value;
    if (!text.trim() || this.saving) return;
    this.saving = true;
    this.saveBtn.disabled = true;
    try {
      const source = this.source.value.trim();
      const res = await api.post('/api/broker', { text, date: this.entryDate.value || null, source, texts: this.keepTexts.checked });
      try { localStorage.setItem('tto.broker.source', source); } catch (e) { /* ignore */ }
      toast(res.saved + ' satır kaydedildi' + (res.skipped ? ' · ' + res.skipped + ' satır zaten kayıtlıydı' : ''), res.saved ? 'ok' : '', 3600);
      this.text.value = '';
      this.draft = '';
      this.parsed = null;
      this.seq += 1;
      this.showPreview();
      // show where the lines went when that is not what is on screen
      const days = res.dates || [];
      const inView = days.every((x) => x >= this.date && x <= (this.to || this.date));
      if (days.length && !inView) this.show(days[0], days.length > 1 ? days[days.length - 1] : null);
      else this.ctx.refreshNow();
    } catch (err) {
      errorToast(err);
      this.saveBtn.disabled = false;
    } finally { this.saving = false; }
  }
}
