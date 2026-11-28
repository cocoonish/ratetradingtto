// Kâğıt Fiyat Yükleme (tto/fiyatyukleme.py): the desk's daily price upload.  The user's own list of bonds (ISIN, the
// catalog's description, maturity) with a bid and an ask spread each - or the defaults - and where its sides start in
// Bloomberg's prices (Mid, or Bid/Ask: Bloomberg's bid and ask, the spreads each on its own side), BBG / İhale, the morning's
// auction text pasted, Hesapla: every bond at t0 (today's value date) with its two sides, every cell editable (a yield
// edited gives its price and the other way round, by the server's BIST conventions), Kaydet (txt): the desk's file
// "ISIN,pricebid,priceask,yieldbid,yieldask" (bills and zero coupons by their yields, the rest by their prices, the
// other two 0), downloaded and kept for a second download today.  An auction line the page cannot read is named once
// (desk-wide) and known from then on.
import { api } from '../api.js';
import { h, clear, toast, errorToast, foldNote } from '../ui.js';
import { num, parseNumber } from '../format.js';
import { bondCardLinks } from '../bonds.js';

const isNum = (v) => typeof v === 'number' && isFinite(v);
const n3 = (v) => (isNum(v) ? num(v, 3, false) : '');
const day = (iso) => (iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4) : '');
const f3 = (v) => v.toFixed(3);                       // the file's figures: three decimals, a dot
const SIDES = [['bid', 'yield', 'fy-bid-y'], ['ask', 'yield', 'fy-ask-y'], ['bid', 'price', 'fy-bid-p'], ['ask', 'price', 'fy-ask-p']];
// where a bond's two sides start in Bloomberg's prices (the desk, 23.11.2026: "... mid'den mi, bid/asktan mı ... Default mid")
const BASES = [['mid', 'Mid'], ['bidask', 'Bid/Ask']];
// the default spreads' boxes (the desk's: one setting each, for every bond without its own)
const DEFS = [['yield_bid', 'Getiri bid (bp)'], ['yield_ask', 'Getiri ask (bp)'], ['price_bid', 'Fiyat bid'], ['price_ask', 'Fiyat ask'],
  ['euro_bid', 'Eurobond bid (bp)'], ['euro_ask', 'Eurobond ask (bp)']];
const BASE_TIP = 'Mid (varsayılan): iki taraf da mid\'den, spread\'ler iki yanına. Bid/Ask: bid tarafı Bloomberg\'in bid\'inden, ask tarafı '
  + 'ask\'inden; spread\'ler her biri kendi tarafına (0 ise ekrandaki fiyat). DİBS RV\'deki kâğıt DİBS RV\'nin bid / ask\'ını kullanır (yeni '
  + 'maliyet yok); diğer DİBS ve Eurobond için Hesapla\'da Bloomberg\'e PX_BID / PX_ASK sorulur (kâğıt başına 2 hit, 5 dakika saklanır). '
  + 'Canlı emir yoksa (–), bid = ask ise ya da taraf yoksa satır mid\'den fiyatlanır ve söyler. DİBS\'te BBG modunda, Eurobond\'da her modda.';

/** A panel of the page: the page's whole width, or (``fit``) as wide as what it holds - the list, the fixed prices, the
 *  file and the labels are narrow tables, side by side when they fit (27.11.2026, "Düzen"). */
function panel(id, title, note, fit, wait) {
  // (a panel drawn from the server's answer says "hesaplanıyor" until it comes - B7; a note two lines, "devamı" the rest -
  // B2, the desk's 28.11.2026)
  const body = h('div', { class: 'body' }, wait ? h('div', { class: 'empty fy-wait' }, 'hesaplanıyor…') : null);
  const noteEl = note ? h('div', { class: 'note' }, note) : null;
  if (noteEl) foldNote(noteEl);
  const el = h('section', { class: 'panel fy-panel' + (fit ? ' fit' : ' wide'), id }, h('header', null, h('h2', null, title)), body, noteEl);
  return { el, body };
}

/**
 * The control in use in ``box`` (the focused one), to be focused again once ``box`` is drawn again - Chrome drops the
 * focus of a control taken out of the page, and the next Tab started from the top of the box.  Found again by its id or
 * by its row's ISIN and its own ``fy-`` class; focused without scrolling, its text selection as it was (a spread tabbed
 * into is all selected: typing replaces it).  Returns the function that does it.
 */
function keepFocus(box) {
  const a = document.activeElement;
  if (!a || !box.contains(a)) return () => {};
  const row = a.closest('tr[data-isin]');
  const cls = [...a.classList].find((c) => c.startsWith('fy-'));
  const find = a.id ? () => document.getElementById(a.id)
    : row && cls ? () => box.querySelector('tr[data-isin="' + row.dataset.isin + '"] .' + cls) : () => null;
  const text = typeof a.selectionStart === 'number' ? [a.value, a.selectionStart, a.selectionEnd, a.selectionDirection] : null;
  return () => {
    const b = find();
    if (!b || b === document.activeElement || !box.contains(b)) return;
    b.focus({ preventScroll: true });
    if (text && b.value === text[0]) b.setSelectionRange(text[1], text[2], text[3]);
  };
}

/** A line of the file, as the server writes it (the preview before Kaydet; the file itself is the server's). */
export function fileLine(r) {
  const b = r.bid || {}, a = r.ask || {};
  if (r.write === 'yield') {
    if (!isNum(b.yield) || !isNum(a.yield)) return null;
    return r.isin + ',0,0,' + f3(b.yield) + ',' + f3(a.yield);
  }
  if (!isNum(b.price) || !isNum(a.price) || !(b.price > 0 && a.price > 0)) return null;
  return r.isin + ',' + f3(b.price) + ',' + f3(a.price) + ',0,0';
}

export class FiyatYuklemePage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.state = null;
    this.result = null;
    this.saved = null;                                 // the text of the last file saved (the server's)
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools fy-tools', id: 'fy-tools' });
    this.modeBox = h('span', { class: 'seg', id: 'fy-mode', title: 'BBG: Bloomberg\'in son işlemi (bugün değilse son ihale + eğri hareketi) · İhale: sabah yapıştırılan ihale fiyatları' });
    for (const [m, text] of [['bbg', 'BBG'], ['ihale', 'İhale']]) {
      const b = h('button', { type: 'button', id: 'fy-mode-' + m, dataset: { mode: m } }, text);
      b.addEventListener('click', () => this.setMode(m));
      this.modeBox.appendChild(b);
    }
    this.info = h('span', { class: 'muted', id: 'fy-info' });
    const calc = h('button', { class: 'btn primary', type: 'button', id: 'fy-hesapla' }, 'Hesapla');
    calc.addEventListener('click', () => this.calculate());
    const save = h('button', { class: 'btn', type: 'button', id: 'fy-kaydet', title: 'Dosya: ISIN,fiyatbid,fiyatask,yieldbid,yieldask - bono ve kuponsuzlar getiriyle, diğerleri fiyatla; yazılmayanlar 0' }, 'Kaydet (txt)');
    save.addEventListener('click', () => this.save());
    this.again = h('button', { class: 'btn ghost', type: 'button', id: 'fy-again', title: 'Bugün kaydedilen son dosyayı yeniden indir' }, 'Bugünkü dosya');
    this.again.addEventListener('click', () => api.download('/api/fiyat-yukleme/dosya', {}, (this.state || {}).file).catch(errorToast));
    tools.append(h('b', null, 'Kâğıt Fiyat Yükleme'), this.modeBox, this.info, h('span', { class: 'grow' }), calc, save, this.again);
    this.host.appendChild(tools);
    const panels = h('div', { class: 'panels' });
    this.ihale = panel('fy-ihale', 'İhale fiyatları', 'Bono ve kuponsuzlarda değer basit getiri (31.500 = %31,5), diğerlerinde temiz fiyat; .t1 = T+1, .t2 = T+2 valör '
      + '(bugünden, TRY iş günü). Etiket: zc kuponsuz, TLREF TLREF\'e endeksli, cpi TÜFE\'ye endeksli; etiketsiz satır aynı vadeli sabit kuponlu (yoksa bono). '
      + 'Bir kâğıdın .t1 satırı kullanılır, .t2 yalnız .t1 yoksa. Tanınamayan satırın kâğıdını bir kez tanıtın: masa için hep tanınır.');
    this.text = h('textarea', { class: 'inp fy-text', id: 'fy-text', rows: '8', spellcheck: 'false',
      placeholder: 'Auction prices:\n06/01/2027.t1   31.500\n10/02/2027zc.t1   31.700\n13/01/27 TLREF.t1   100.500' });
    this.parse = h('div', { class: 'fy-parse', id: 'fy-parse' });
    this.ihale.body.append(this.text, this.parse);
    this.list = panel('fy-list', 'Kâğıt listesi (masanın)',
      'Liste masanın: herkes aynı listeyi görür; eklenen ya da çıkarılan kâğıt, değişen spread, Mid / Bid/Ask ve varsayılan spread bütün masa için '
      + 'değişir (açık sayfalara da gelir); mod, ihale metni, Hesapla ve kaydedilen dosyalar kişinin kendisinin. Getiriyle kote edilenler (sabit '
      + 'kuponlu, bono, kuponsuz): bid getiri = t0 + bid spread, ask getiri = t0 − ask spread (bp). Fiyatla kote edilenler (TLREF, FRN, TÜFE): bid '
      + 'fiyat = t0 − bid spread, ask fiyat = t0 + ask spread (fiyat puanı). Eurobond (USD / EUR, ISIN\'iyle eklenir): mod ne olursa olsun '
      + 'Bloomberg\'in mid\'inden; bid getiri = mid + bid spread, ask getiri = mid − ask spread (bp, kendi varsayılanı), fiyatlar Bloomberg\'in '
      + 'mid\'ine çapalı sokak kuralıyla. Satırın spread\'i boşsa varsayılan; eksi değer olur (skew). BBG\'den: Mid (varsayılan) ya da Bid/Ask - bid '
      + 'tarafı Bloomberg\'in bid\'inden, ask tarafı ask\'inden, spread\'ler kendi tarafına (DİBS RV dışındaki kâğıtta Hesapla başına 2 hit); Tümü '
      + 'hepsini birden değiştirir.', true);
    this.sabit = panel('fy-sabit', 'Sabit fiyatlar (masanın)',
      'Bu kâğıtlar hesaplanmadan, girildiği gibi yüklenir; liste gibi masanındır, biri değiştirene ya da çıkarana kadar kalır. Yalnız ISIN, bid ve '
      + 'offer gerekir (katalogda olmayan döviz DİBS de olur; vadesi ISIN\'den okunur). Değerler dosyaya yazıldığı birimde: bono ve kuponsuz getiri '
      + '(%, basit), diğerleri temiz fiyat. Aynı ISIN yeniden yapıştırılınca güncellenir. Listede de olan bir kâğıtta sabit fiyat geçerlidir. '
      + 'Hesaplanan bir satırı "Sabitle" ile buraya alabilirsiniz.', true);
    this.result_ = panel('fy-result', 'Fiyatlar · t0', 'Getiriler BIST basit getiri (%), fiyatlar t0 valöründe temiz. Her hücre düzenlenebilir: getiri değişince fiyatı, '
      + 'fiyat değişince getirisi aynı kurallarla yeniden hesaplanır. Dosyaya: bono / kuponsuz getiriyle, diğerleri fiyatla yazılır. Sabit fiyatlı satırdaki '
      + 'değişiklik yalnız bu Hesapla içindir.');
    bondCardLinks(this.ctx, this.result_.body);                  // (a bond's name opens its card)
    this.buildList();
    this.buildSabit();
    this.file = panel('fy-file', 'Dosya (Kaydet\'te yazılacak satırlar)', null, true, true);
    this.labels = panel('fy-labels', 'Tanıtılan ihale etiketleri (masanın)', null, true, true);
    // what the morning's work is done in first - the auction text, the prices at t0 and the file -, the desk's list and its
    // set-up after them (27.11.2026, "Düzen": Fiyatlar · t0 was the fourth of six panels)
    panels.append(this.ihale.el, this.result_.el, this.file.el, this.list.el, this.sabit.el, this.labels.el);
    this.host.appendChild(panels);
  }

  /** The list's own boxes, made once - what is typed in them stays while the desk's list is drawn again: the add box,
   *  the defaults, who changed the list last; the table under them (``drawList``). */
  buildList() {
    this.addText = h('textarea', { class: 'inp', id: 'fy-add-text', rows: '2', spellcheck: 'false', placeholder: 'ISIN ya da ISIN listesi (satır satır ya da virgülle)' });
    const addBtn = h('button', { class: 'btn', type: 'button', id: 'fy-add' }, 'Ekle');
    addBtn.addEventListener('click', () => this.addBonds(this.addText.value));
    const defs = h('div', { class: 'fy-defs', id: 'fy-defs' }, h('span', { class: 'muted' }, 'Varsayılan spread:'));
    this.defInputs = {};
    for (const [k, label] of DEFS) {
      const inp = h('input', { class: 'inp', id: 'fy-def-' + k.replace('_', '-'), size: '6', inputmode: 'decimal' });
      inp.addEventListener('input', () => { inp.dataset.typed = '1'; });          // (as typed until saved: drawDefs)
      this.defInputs[k] = inp;
      defs.append(h('label', null, label + ' ', inp));
    }
    const defSave = h('button', { class: 'btn', type: 'button', id: 'fy-def-save' }, 'Kaydet');
    defSave.addEventListener('click', () => this.saveDefaults());
    defs.appendChild(defSave);
    this.deskLine = h('div', { class: 'muted fy-desk', id: 'fy-desk' });
    this.listBox = h('div', { class: 'fy-list-box' });
    this.list.body.append(h('div', { class: 'fy-add' }, this.addText, addBtn), defs, this.deskLine, this.listBox);
    bondCardLinks(this.ctx, this.list.body);
    this.waitForFocus(this.listBox, () => this.drawList());
  }

  /** Sabit fiyatlar' own boxes, made once: the box Excel's rows are pasted in (ISIN, bid, offer - the cells between, an
   *  empty column, a yield, a stock, skipped by the server), what the last paste did; the table under them (``drawSabit``). */
  buildSabit() {
    this.sabitText = h('textarea', { class: 'inp fy-sabit-text', id: 'fy-sabit-text', rows: '4', spellcheck: 'false',
      placeholder: 'Excel\'den ISIN, Bid ve Offer\'ı kopyalayıp yapıştırın - her satır bir kâğıt (aradaki boş sütun, getiri ve stok sütunları atlanır).\n'
        + 'TRT191127F19\t99.483\t\t99.726' });
    const go = h('button', { class: 'btn', type: 'button', id: 'fy-sabit-yapistir' }, 'Ekle / Güncelle');
    go.addEventListener('click', () => this.pasteFixed(this.sabitText.value));
    this.rapor = h('div', { class: 'fy-sabit-rapor', id: 'fy-sabit-rapor' });
    this.sabitBox = h('div', { class: 'fy-sabit-box' });
    this.sabit.body.append(h('div', { class: 'fy-add' }, this.sabitText, go), this.rapor, this.sabitBox);
    this.waitForFocus(this.sabitBox, () => this.drawSabit());
  }

  /** Another user's change waits while this user works in ``box`` (the focus in it: a spread being typed, a select) -
   *  ``draw`` once the focus has left it (not when only the window lost it: the focus comes back there). */
  waitForFocus(box, draw) {
    box.addEventListener('focusout', () => setTimeout(() => {
      if (box.dataset.waiting && !box.contains(document.activeElement)) draw();
    }, 0));
  }

  async load() {
    this.state = await api.get('/api/fiyat-yukleme');
    this.text.value = this.state.text || '';
    this.drawAll();
  }

  // Another user's change of the desk's list - its bonds, spreads, Mid / Bid/Ask, defaults, fixed prices - comes on a new
  // generation: asked for by the list's revision (unchanged: a short answer).  This user's own work stays as it is: what
  // is typed in the boxes, the auction text, a Hesapla and its edits.
  async refresh() {
    if (!this.state) return;
    const got = await api.get('/api/fiyat-yukleme', { rev: this.state.rev });
    if (got && !got.unchanged) this.takeDesk(got);
  }

  /** The desk's list as another user left it (only that of what the server says: this page's mode stays); a Hesapla's
   *  result said to be stale. */
  takeDesk(got) {
    const st = this.state;
    if (!st || (typeof got.rev === 'number' && typeof st.rev === 'number' && got.rev <= st.rev)) return;    // (not newer)
    this.took(Object.assign(st, { list: got.list, fixed: got.fixed, defaults: got.defaults, rev: got.rev, desk: got.desk }), null);
    this.markStale('Masanın listesi değişti: yeniden Hesapla');
  }

  /** A state the server answered - an action's (the desk's list as it is now, another user's changes in it too) or
   *  another user's change: the table the action was in (``now``) drawn at once, the other one too unless this user is
   *  working in it (then once the focus leaves it), the defaults' boxes not typed in, who changed the list last. */
  took(got, now) {
    this.state = got;
    for (const [box, draw] of [[this.listBox, () => this.drawList()], [this.sabitBox, () => this.drawSabit()]]) {
      if (box === now || !box.contains(document.activeElement)) draw(); else box.dataset.waiting = '1';
    }
    this.drawDefs();
    this.drawDesk();
  }

  drawAll() {
    this.drawMode();
    this.drawDefs();
    this.drawDesk();
    this.drawList();
    this.drawSabit();
    this.drawResult();
    this.drawFile();
    this.drawLabels();
  }

  drawMode() {
    const st = this.state || {};
    for (const b of this.modeBox.querySelectorAll('button')) b.classList.toggle('on', b.dataset.mode === st.mode);
    this.ihale.el.classList.toggle('hidden', st.mode !== 'ihale');
    this.info.textContent = ' · t0 ' + day(st.t0) + (st.live ? '' : ' · kayıtlı veri (Bloomberg yok)');
  }

  async setMode(m) {
    if (!this.state || this.state.mode === m) return;
    try {
      this.took(await api.post('/api/fiyat-yukleme/ayar', { mode: m }), null);
      this.result = null;
      this.drawMode();
      this.drawResult();
      this.drawFile();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ the list
  drawList() {
    const st = this.state || {};
    delete this.listBox.dataset.waiting;
    const refocus = keepFocus(this.listBox);
    const body = clear(this.listBox);
    const t = h('table', { class: 'plain fy', id: 'fy-list-table' });
    // Mid or Bid/Ask, each bond's own; "Tümü" sets every bond of the list at once
    const all = h('select', { class: 'inp fy-base-all', id: 'fy-base-all', title: 'Listedeki bütün kâğıtları birden Mid ya da Bid/Ask yap' },
      h('option', { value: '' }, 'Tümü…'), ...BASES.map(([v, x]) => h('option', { value: v }, x)));
    all.addEventListener('change', () => { if (all.value) this.saveBase(null, all.value); });
    t.appendChild(h('tr', null, ...[['ISIN', 'l'], ['Kâğıt', 'l'], ['Açıklama', 'l'], ['Vade', ''], ['Tür', 'l'], ['Bid spread', ''], ['Ask spread', ''], ['Birim', 'l']]
      .map(([x, c]) => h('th', { class: c || null }, x)), h('th', { class: 'l fy-base-head', title: BASE_TIP }, 'BBG\'den ', all), h('th', null, '')));
    for (const r of st.list || []) {
      const tr = h('tr', { class: 'fy-item', dataset: { isin: r.isin } });
      const sp = r.spread || {};
      const spIn = (side) => {
        const own = sp['own_' + side];
        const inp = h('input', { class: 'inp fy-sp-' + side, value: own ? num(sp[side], sp.unit === 'bp' ? 1 : 3, false) : '', size: '6', inputmode: 'decimal',
          placeholder: num(sp[side], sp.unit === 'bp' ? 1 : 3, false), title: own ? 'Bu kâğıdın kendi spread\'i (boşaltınca varsayılan)' : 'Varsayılan (yazınca bu kâğıdın olur)' });
        inp.addEventListener('change', () => this.saveSpread(r.isin, side, inp.value));
        return h('td', null, inp);
      };
      const del = h('td', { class: 'act fy-del', title: 'Listeden çıkar: ' + r.isin }, '×');
      del.addEventListener('click', () => this.removeBond(r.isin));
      const base = h('select', { class: 'inp fy-base', title: BASE_TIP },
        ...BASES.map(([v, x]) => h('option', { value: v, selected: (r.base || 'mid') === v }, x)));
      base.addEventListener('change', () => this.saveBase(r.isin, base.value));
      // (the bond's name opens its card, its ISIN in the tip - the same on every bond table, 28.11.2026)
      tr.append(h('td', { class: 'l' }, r.isin), h('td', { class: 'l b' + (r.kind === 'euro' ? '' : ' bondlink'), title: r.kind === 'euro' ? null : r.isin + ' · tıklayınca kâğıt kartı' }, r.label || ''),
        h('td', { class: 'l fy-name' }, r.name || ''),
        h('td', null, day(r.maturity)), h('td', { class: 'l fy-kind' }, (r.kind_text || '') + (r.kind === 'euro' ? ' · ' + (r.ccy || '') : '')),
        spIn('bid'), spIn('ask'), h('td', { class: 'l muted' }, sp.unit === 'bp' ? (r.kind === 'euro' ? 'bp (BBG getirisi)' : 'bp (getiri)') : 'fiyat'),
        h('td', { class: 'l' }, base), del);
      t.appendChild(tr);
    }
    if (!(st.list || []).length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '10' }, 'Liste boş: yukarıya ISIN yazıp Ekle')));
    body.appendChild(t);
    refocus();
  }

  /** The defaults' boxes: the desk's figures - a box typed in and not saved yet keeps what is in it. */
  drawDefs() {
    const d = (this.state || {}).defaults || {};
    for (const [k, inp] of Object.entries(this.defInputs)) {
      if (!inp.dataset.typed) inp.value = num(d[k], k.startsWith('price') ? 3 : 1, false);
    }
  }

  /** Who changed the desk's list last, and when. */
  drawDesk() {
    const d = (this.state || {}).desk || {};
    this.deskLine.textContent = d.by ? 'Masanın listesi · son değişiklik: ' + this.ctx.displayName(d.by) + ', ' + day(d.at) + ' '
      + String(d.at || '').slice(11, 16) : '';
  }

  async addBonds(text) {
    if (!String(text || '').trim()) { toast('ISIN yazın', 'err'); return; }
    try {
      const got = await api.post('/api/fiyat-yukleme/ekle', { isins: text });
      this.took(got, this.listBox);
      if (got.added.length) toast(got.added.length + ' kâğıt eklendi', 'ok');
      if (got.skipped.length) toast('Zaten listede: ' + got.skipped.join(', '));
      for (const r of got.refused || []) toast(r.isin + ': ' + r.text, 'err', 7000);
      if (got.added.length && this.addText) this.addText.value = '';
    } catch (err) { errorToast(err); }
  }

  async removeBond(isin) {
    try {
      this.took(await api.post('/api/fiyat-yukleme/cikar', { isin }), this.listBox);
      if (this.result) {
        this.result.rows = this.result.rows.filter((r) => r.isin !== isin);
        this.drawResult();
        this.drawFile();
      }
    } catch (err) { errorToast(err); }
  }

  async saveSpread(isin, side, value) {
    try {
      this.took(await api.post('/api/fiyat-yukleme/ayar', { spreads: { [isin]: { [side]: value.trim() } } }), this.listBox);
      this.markStale();
    } catch (err) { errorToast(err); this.drawList(); }
  }

  /** A bond's Mid / Bid/Ask (``isin`` null: "Tümü", every bond of the list), kept with the list by its ISIN. */
  async saveBase(isin, base) {
    try {
      this.took(await api.post('/api/fiyat-yukleme/ayar', isin ? { bases: { [isin]: base } } : { base_all: base }), this.listBox);
      this.markStale('Mid / Bid/Ask değişti: yeniden Hesapla');
    } catch (err) { errorToast(err); this.drawList(); }
  }

  // the boxes typed in (none: all of them) - another user's change of the others stands
  async saveDefaults() {
    const defaults = {};
    const typed = Object.entries(this.defInputs).filter(([, inp]) => inp.dataset.typed);
    for (const [k, inp] of typed.length ? typed : Object.entries(this.defInputs)) defaults[k] = inp.value.trim();
    try {
      const got = await api.post('/api/fiyat-yukleme/ayar', { defaults });
      for (const inp of Object.values(this.defInputs)) delete inp.dataset.typed;
      this.took(got, this.listBox);
      this.markStale();
      toast('Varsayılan spread kaydedildi', 'ok');
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ fixed prices ("Sabit fiyat")
  drawSabit() {
    const st = this.state || {};
    delete this.sabitBox.dataset.waiting;
    const refocus = keepFocus(this.sabitBox);
    const body = clear(this.sabitBox);
    const t = h('table', { class: 'plain fy fy-sabit-tbl', id: 'fy-sabit-table' });
    t.appendChild(h('tr', null, ...[['ISIN', 'l'], ['Açıklama', 'l'], ['Vade', ''], ['Birim', 'l'], ['Bid', ''], ['Offer', ''], ['Dosya satırı', 'l'], ['', '']]
      .map(([x, c]) => h('th', { class: c || null }, x))));
    for (const r of st.fixed || []) {
      const tr = h('tr', { class: 'fy-sabit-item', dataset: { isin: r.isin } });
      const tip = 'Değiştirince kaydedilir (' + (r.unit === 'yield' ? 'getiri, %' : 'temiz fiyat') + ')';
      const bi = h('input', { class: 'inp fy-sabit-bid', value: n3(r.bid), size: '9', inputmode: 'decimal', title: tip });
      const ai = h('input', { class: 'inp fy-sabit-ask', value: n3(r.ask), size: '9', inputmode: 'decimal', title: tip });
      for (const inp of [bi, ai]) inp.addEventListener('change', () => this.saveFixed(r.isin, bi.value, ai.value));
      const del = h('td', { class: 'act fy-sabit-del', title: 'Sabit fiyatı kaldır: ' + r.isin }, '×');
      del.addEventListener('click', () => this.removeFixed(r.isin));
      const desc = (r.name || r.kind_text || '') + (r.kind === 'euro' ? ' · ' + (r.ccy || '') : '');
      tr.append(h('td', { class: 'l b' }, r.isin), h('td', { class: 'l fy-name', title: r.listed ? 'Listede de var: sabit fiyat geçerli' : null },
        desc + (r.listed ? ' (listede de)' : '')), h('td', null, day(r.maturity)),
      h('td', { class: 'l fy-sabit-unit' }, r.unit === 'yield' ? 'getiri %' : 'temiz fiyat'), h('td', null, bi), h('td', null, ai),
      h('td', { class: 'l fy-sabit-line', title: 'Girildi: ' + (r.at || '').slice(0, 16) }, r.line || ''), del);
      t.appendChild(tr);
    }
    if (!(st.fixed || []).length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '8' }, 'Sabit fiyatlı kâğıt yok')));
    body.appendChild(t);
    refocus();
  }

  /** What the last paste did: added, updated, the lines that could not be read and why. */
  drawRapor() {
    const rep = clear(this.rapor);
    const p = this.lastPaste;
    if (!p) return;
    rep.appendChild(h('div', { class: 'muted' }, p.added.length + ' kâğıt eklendi · ' + p.updated.length + ' güncellendi · ' + p.bad.length
      + ' satır okunamadı' + (p.ignored ? ' · ' + p.ignored + ' satır yok sayıldı (başlık, grup adı)' : '')));
    for (const b of p.bad) rep.appendChild(h('div', { class: 'fy-sabit-bad' }, 'Satır ' + b.n + ': ' + b.text + ' - ' + b.why));
  }

  async pasteFixed(text) {
    if (!String(text || '').trim()) { toast('Excel\'den ISIN, bid ve offer\'ı yapıştırın', 'err'); return; }
    try {
      const got = await api.post('/api/fiyat-yukleme/sabit-yapistir', { text });
      this.lastPaste = got.pasted;
      this.drawRapor();
      this.took(got, this.sabitBox);
      if (!got.pasted.bad.length) this.sabitText.value = '';          // (with a line left to fix, the text stays)
      this.markStale();
      toast(got.pasted.added.length + ' eklendi, ' + got.pasted.updated.length + ' güncellendi' + (got.pasted.bad.length ? ', ' + got.pasted.bad.length
        + ' satır okunamadı' : ''), got.pasted.bad.length ? 'err' : 'ok');
    } catch (err) { errorToast(err); }
  }

  async saveFixed(isin, bidText, askText) {
    const read = (v) => (typeof v === 'number' ? v : parseNumber(String(v || ''), true));
    const bid = read(bidText), ask = read(askText);
    if (!isin) { toast('ISIN yazın', 'err'); return; }
    if (!isNum(bid) || !isNum(ask)) { toast('Bid ve ask\'i sayı olarak girin', 'err'); return; }
    try {
      const got = await api.post('/api/fiyat-yukleme/sabit', { isin, bid, ask });
      this.took(got, this.sabitBox);
      this.markStale();
      toast(isin + ': sabit fiyat kaydedildi', 'ok');
      if (got.crossed) toast(isin + ': bid ask\'ten iyi (ters kotasyon)', 'err', 6000);
    } catch (err) { errorToast(err); this.drawSabit(); }
  }

  async removeFixed(isin) {
    try {
      this.took(await api.post('/api/fiyat-yukleme/sabit-sil', { isin }), this.sabitBox);
      this.markStale();
    } catch (err) { errorToast(err); }
  }

  /** "Sabitle": a computed row's bid / ask as they are now (edited or not), in the file's unit, stored as its fixed figures. */
  async fixRow(r) {
    const b = r.bid || {}, a = r.ask || {};
    const bid = r.write === 'yield' ? b.yield : b.price, ask = r.write === 'yield' ? a.yield : a.price;
    if (!isNum(bid) || !isNum(ask)) { toast('Sabitlenecek bid / ask yok', 'err'); return; }
    await this.saveFixed(r.isin, bid, ask);
  }

  markStale(text) {
    const info = document.getElementById('fy-result-info');
    if (this.result && info) info.textContent = text || 'Spread değişti: yeniden Hesapla';
  }

  // ------------------------------------------------------------------ Hesapla
  async calculate() {
    const st = this.state || {};
    const body = { mode: st.mode };
    if (st.mode === 'ihale') body.text = this.text.value;
    const btn = document.getElementById('fy-hesapla');
    if (btn) btn.disabled = true;
    try {
      this.result = await api.post('/api/fiyat-yukleme/hesapla', body);
      this.saved = null;
      this.drawParse();
      this.drawResult();
      this.drawFile();
    } catch (err) { errorToast(err); } finally { if (btn) btn.disabled = false; }
  }

  drawParse() {
    const body = clear(this.parse);
    const p = (this.result || {}).parse;
    if (!p) return;
    body.appendChild(h('div', { class: 'fy-parse-sum', id: 'fy-parse-sum' }, p.recognised + ' satır tanındı · ' + p.unrecognised + ' satır tanınamadı · '
      + (p.ignored || []).length + ' satır yok sayıldı · ihale değeri kaydedildi: ' + p.stored));
    const t = h('table', { class: 'plain fy', id: 'fy-parse-table' });
    t.appendChild(h('tr', null, ...[['Satır', ''], ['Etiket', 'l'], ['Valör', ''], ['Değer', ''], ['Kâğıt', 'l'], ['Durum', 'l']].map(([x, c]) => h('th', { class: c || null }, x))));
    const inList = new Set(((this.state || {}).list || []).map((r) => r.isin));
    for (const ln of p.lines || []) {
      const tr = h('tr', { class: 'fy-line' + (ln.why ? ' fy-bad' : ln.used ? '' : ' fy-unused'), dataset: { n: String(ln.n) } });
      const state = h('td', { class: 'l fy-state' });
      if (ln.why) {
        state.append(h('span', { class: 'fy-why' }, 'Tanınamadı: ' + ln.why));
        if (ln.key) {
          const pick = h('select', { class: 'inp', id: 'fy-pick-' + ln.n }, h('option', { value: '' }, '— yakın vadeli kâğıtlar —'),
            ...(ln.near || []).map((b) => h('option', { value: b.isin }, b.label + ' · ' + b.isin + ' · ' + (b.name || ''))));
          const typed = h('input', { class: 'inp', id: 'fy-isin-' + ln.n, placeholder: 'ya da ISIN', size: '14' });
          const go = h('button', { class: 'btn sm', type: 'button', id: 'fy-tanit-' + ln.n }, 'Tanıt');
          go.addEventListener('click', () => this.nameLine(ln, (typed.value || '').trim() || pick.value));
          state.append(' ', pick, ' ', typed, ' ', go);
        }
      } else {
        state.append(ln.used ? 'Tanındı (' + ln.how + ')' : 'Kullanılmadı: ' + (ln.unused || ''));
        if (ln.isin && !inList.has(ln.isin)) {
          const addBtn = h('button', { class: 'btn sm fy-addline', type: 'button', dataset: { isin: ln.isin } }, '+ Listeye ekle');
          addBtn.addEventListener('click', () => this.addBonds(ln.isin));
          state.append(' ', addBtn);
        }
      }
      tr.append(h('td', null, String(ln.n)), h('td', { class: 'l b' }, (ln.label || ln.text) + (ln.tn ? '.t' + ln.tn : '')),
        h('td', null, day(ln.value_date)), h('td', null, n3(ln.value)), h('td', { class: 'l' }, ln.isin ? ln.isin + ' · ' + (ln.short || '') : ''), state);
      t.appendChild(tr);
    }
    body.appendChild(t);
    if ((p.ignored || []).length) {
      body.appendChild(h('div', { class: 'muted fy-ignored', id: 'fy-ignored' }, 'Yok sayılan satırlar: ' + p.ignored.map((x) => x.text).join(' · ')));
    }
  }

  async nameLine(ln, isin) {
    if (!isin) { toast('Listeden bir kâğıt seçin ya da ISIN yazın', 'err'); return; }
    try {
      const got = await api.post('/api/fiyat-yukleme/tanit', { label: ln.key, isin });
      this.state.labels = got.labels;
      this.drawLabels();
      toast(ln.key + ' → ' + isin + ' tanıtıldı (masa için)', 'ok');
      await this.calculate();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ the prices
  drawResult() {
    const body = clear(this.result_.body);
    const res = this.result;
    if (!res) {
      body.appendChild(h('div', { class: 'empty', id: 'fy-empty' }, 'Hesapla\'ya basın: listedeki kâğıtlar ' + ((this.state || {}).mode === 'bbg'
        ? 'Bloomberg\'in son işleminden (DİBS RV; listede olmayanlar için tek seferlik istek, kâğıt başına 2 hit; Bid/Ask seçilenler bid / ask\'ından, '
          + 'DİBS RV dışındakilere 2 hit daha)' : 'yapıştırılan ihale fiyatlarından') + ' t0\'da fiyatlanır.'));
      return;
    }
    // Bid/Ask: the bonds set so, how many were priced from their sides (the others from the mid: their rows say why)
    const sidesText = (x) => 'Bid/Ask ' + x.n + ' kâğıt (' + x.from_sides + ' bid / ask\'tan' + (x.n > x.from_sides ? ', ' + (x.n - x.from_sides)
      + ' mid\'den: satırda neden' : '') + ')';
    const parts = [(res.mode === 'bbg' ? 'BBG' : 'İhale') + ' · t0 ' + day(res.t0) + ' · ' + (res.time || '')];
    if (res.bbg) {
      const b = res.bbg, ba = b.bidask;
      parts.push(b.why ? 'Bloomberg: ' + b.why : 'Bloomberg\'e ' + b.asked + ' kâğıt soruldu' + (ba && ba.asked ? ', ' + ba.asked + ' kâğıdın bid / ask\'ı' : '')
        + ' (' + b.hits + ' hit), ' + b.cached + ' son 5 dakikadan');
      parts.push('DİBS RV\'den ' + b.trading);
      if (ba) parts.push(sidesText(ba) + (ba.why && ba.why !== b.why ? ': bid / ask sorulamadı (' + ba.why + ')' : ''));
    }
    if (res.euro) {
      const e = res.euro;
      parts.push(e.why ? 'Eurobond: ' + e.why : 'Eurobond mid\'i: ' + e.asked + ' soruldu (' + e.hits + ' hit), ' + e.cached + ' son 5 dakikadan'
        + (e.sides ? ', ' + e.sides + ' kâğıtta PX_MID boş: bid / ask\'ın ortası' : ''));
      if (e.bidask) parts.push('Eurobond ' + sidesText(e.bidask));
    }
    if (res.fixed) parts.push(res.fixed + ' sabit fiyat (hesaplanmadı, Bloomberg\'e sorulmadı)');
    if (res.curve) parts.push(res.curve + ' kâğıt eğri fiyatıyla (başka fiyatı yoktu: Kâğıt Fiyatlama\'nın eğrisi, kaydetmeden önce kontrol edin)');
    body.appendChild(h('div', { class: 'muted fy-result-info', id: 'fy-result-info' }, parts.join(' · ')));
    const t = h('table', { class: 'plain fy', id: 'fy-table' });
    t.appendChild(h('tr', null, ...[['Kâğıt', 'l'], ['ISIN', 'l'], ['Açıklama', 'l'], ['Vade', ''], ['t0 / mid getiri %', ''], ['t0 / mid fiyat', ''], ['Bid getiri %', 'fy-sep'],
      ['Ask getiri %', ''], ['Bid fiyat', 'fy-sep'], ['Ask fiyat', ''], ['Dosyaya', 'l'], ['', ''], ['Nasıl', 'l']].map(([x, c]) => h('th', { class: c || null }, x))));
    for (const r of res.rows || []) t.appendChild(this.rowEl(r));
    if (!(res.rows || []).length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '13' }, 'Liste boş')));
    body.appendChild(t);
  }

  rowEl(r) {
    const tr = h('tr', { class: 'fy-row' + (r.priced ? '' : ' fy-off') + (r.edited ? ' fy-edited' : '') + (r.note ? ' fy-warn' : '') + (r.fixed ? ' fy-fixed' : '')
      + (r.curve ? ' fy-curve' : ''), dataset: { isin: r.isin } });
    const t0 = r.t0 || {};
    const fixedTip = 'Sabit fiyat: buradaki değişiklik yalnız bu Hesapla için; kayıtlı sabit değer değişmez (Sabit fiyat bölümünden değiştirin)';
    const cells = SIDES.map(([side, field, cls]) => {
      const v = (r[side] || {})[field];
      const off = field === 'yield' && r.quoted !== 'yield';
      const inp = h('input', { class: 'inp ' + cls, value: off ? '' : n3(v), size: '8', inputmode: 'decimal', disabled: off,
        placeholder: off ? '–' : '', title: off ? 'Fiyatla kote edilir: getirisi yok' : (r.fixed ? fixedTip + '. ' : '')
          + (field === 'yield' ? 'Getiri değişince fiyatı yeniden hesaplanır' : 'Fiyat değişince getirisi yeniden hesaplanır') });
      if (!off) inp.addEventListener('change', () => this.edit(r, side, field, inp));
      return h('td', { class: field === 'yield' && side === 'bid' || field === 'price' && side === 'bid' ? 'fy-sep' : null }, inp);
    });
    // a fixed row says so; a computed one can be fixed as it is now ("Sabitle")
    let act;
    if (r.fixed) {
      act = h('td', { class: 'l fy-sabit-mark', title: fixedTip }, 'sabit fiyat');
    } else {
      const btn = h('button', { class: 'btn sm fy-sabitle', type: 'button', title: 'Bu satırın şimdiki bid / ask\'ini (düzenlendiyse düzenlenmiş hâlini) sabit fiyat olarak kaydet',
        disabled: !r.priced }, 'Sabitle');
      btn.addEventListener('click', () => this.fixRow(r));
      act = h('td', null, btn);
    }
    const how = [r.how || '', r.why ? (r.how ? ' · ' : '') + r.why : '', r.note ? ' · ' + r.note : ''].join('');
    const midTip = r.kind === 'euro' && !r.fixed ? 'Bloomberg\'in mid\'i (valör ' + day(r.settle) + '); çapa farkı ' + (isNum(r.anchor) ? num(r.anchor, 3, false) : '–')
      : 't0 (' + day(r.value_date) + ')';
    tr.append(h('td', { class: 'l b' + (r.kind === 'euro' ? '' : ' bondlink'), title: r.kind === 'euro' ? null : r.isin + ' · tıklayınca kâğıt kartı' }, r.label || ''),
      h('td', { class: 'l' }, r.isin), h('td', { class: 'l fy-name' }, r.name || ''), h('td', null, day(r.maturity)),
      h('td', { class: 'fy-t0-y', title: midTip }, n3(t0.yield)), h('td', { class: 'fy-t0-p', title: midTip }, n3(t0.price)), ...cells,
      h('td', { class: 'l fy-write' }, r.write === 'yield' ? 'getiri' : 'fiyat'), act,
      // a bond priced off the curve (no trade, no auction): said first, so the desk sees it before saving
      h('td', { class: 'l fy-how', title: how }, r.curve ? h('b', { class: 'fy-curve-mark', title: 'Başka fiyatı yoktu: Kâğıt Fiyatlama\'nın eğri fiyatı ('
        + r.curve.label + ') ve satırın spreadleri' }, r.curve.mark || 'eğri fiyatı') : '', r.curve ? ' · ' : '', how));
    return tr;
  }

  async edit(r, side, field, inp) {
    const text = inp.value.trim();
    const v = text === '' ? null : parseNumber(text, true);
    if (text !== '' && v === null) { toast('Bir sayı girin', 'err'); inp.value = n3((r[side] || {})[field]); return; }
    try {
      if (v === null) {
        r[side] = { yield: null, price: null };          // (a side emptied: not written)
      } else if (r.quoted !== 'yield') {
        r[side] = { yield: null, price: v };
      } else {
        // (a Eurobond: the street convention at its settlement, anchored to Bloomberg's mid as Hesapla found it)
        const body = { isin: r.isin, field, value: v };
        if (r.kind === 'euro') Object.assign(body, { settle: r.settle, anchor: r.anchor });
        const got = await api.post('/api/fiyat-yukleme/cevir', body);
        r[side] = { yield: got.yield, price: got.price };
      }
      r.edited = true;
      const old = this.result_.body.querySelector('tr.fy-row[data-isin="' + r.isin + '"]');
      if (old) {
        const refocus = keepFocus(this.result_.body);               // (Tab went on to the row's next cell: it stays there)
        old.replaceWith(this.rowEl(r));
        refocus();
      }
      this.saved = null;
      this.drawFile();
    } catch (err) { errorToast(err); inp.value = n3((r[side] || {})[field]); }
  }

  // ------------------------------------------------------------------ the file
  drawFile() {
    const body = clear(this.file.body);
    const st = this.state || {};
    const res = this.result;
    let text = this.saved;
    const left = [];
    if (text === null || text === undefined) {
      const lines = [];
      for (const r of (res || {}).rows || []) {
        const line = fileLine(r);
        if (line) lines.push(line); else left.push(r.label || r.isin);
      }
      text = lines.map((x) => x + '\r\n').join('');
    }
    body.appendChild(h('div', { class: 'muted fy-file-name', id: 'fy-file-name' }, (this.saved ? 'Kaydedildi: ' : 'Önizleme: ') + (st.file || '')
      + (left.length ? ' · yazılmayacak (fiyatı yok): ' + left.join(', ') : '')));
    const pre = h('pre', { class: 'fy-txt', id: 'fy-txt', dataset: { saved: this.saved ? '1' : '0' } });
    pre.textContent = text || '';
    body.appendChild(pre);
    const saves = st.saved || [];
    if (saves.length) {
      body.appendChild(h('div', { class: 'muted fy-saves', id: 'fy-saves' }, 'Bugün kaydedilenler: ' + saves.map((x) => (x.at || '').slice(11, 16) + ' (' + x.n + ' satır)').join(' · ')));
    }
  }

  async save() {
    const res = this.result;
    if (!res || !(res.rows || []).length) { toast('Önce Hesapla', 'err'); return; }
    const rows = res.rows.map((r) => ({ isin: r.isin, bid_price: (r.bid || {}).price, ask_price: (r.ask || {}).price, bid_yield: (r.bid || {}).yield,
      ask_yield: (r.ask || {}).yield }));
    try {
      const got = await api.post('/api/fiyat-yukleme/kaydet', { rows });
      this.saved = got.text;
      this.state.saved = got.saved;
      this.drawFile();
      toast('Kaydedildi: ' + got.name + ' (' + got.lines.length + ' satır)', 'ok');
      if ((got.left_out || []).length) toast('Dosyaya yazılmadı: ' + got.left_out.map((x) => x.label + ' (' + x.why + ')').join(', '), 'err', 7000);
      if ((got.crossed || []).length) toast('Bid ask\'ten iyi (ters kotasyon): ' + got.crossed.join(', '), 'err', 7000);
      await api.download('/api/fiyat-yukleme/dosya', {}, got.name);
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ the desk's labels
  drawLabels() {
    const body = clear(this.labels.body);
    const rows = (this.state || {}).labels || [];
    if (!rows.length) {
      body.appendChild(h('div', { class: 'empty' }, 'Henüz tanıtılan etiket yok: ihale metninde tanınamayan bir satırın kâğıdını seçip Tanıt\'a basın.'));
      return;
    }
    const t = h('table', { class: 'plain fy', id: 'fy-labels-table' });
    t.appendChild(h('tr', null, ...[['Etiket', 'l'], ['ISIN', 'l'], ['Kâğıt', 'l'], ['Açıklama', 'l'], ['Tanıtan', 'l'], ['Ne zaman', 'l'], ['', '']]
      .map(([x, c]) => h('th', { class: c || null }, x))));
    for (const x of rows) {
      const del = h('td', { class: 'act fy-label-del', title: 'Bu etiketi unut (masa için)', dataset: { key: x.key } }, '×');
      del.addEventListener('click', async () => {
        try {
          const got = await api.post('/api/fiyat-yukleme/tanit', { label: x.key, isin: '' });
          this.state.labels = got.labels;
          this.drawLabels();
        } catch (err) { errorToast(err); }
      });
      t.appendChild(h('tr', { dataset: { key: x.key } }, h('td', { class: 'l b' }, x.key), h('td', { class: 'l' }, x.isin || ''), h('td', { class: 'l' }, x.short || ''),
        h('td', { class: 'l' }, x.name || ''), h('td', { class: 'l' }, this.ctx.displayName(x.by)), h('td', { class: 'l' }, (x.at || '').slice(0, 16)), del));
    }
    body.appendChild(t);
  }

  destroy() {}
}
