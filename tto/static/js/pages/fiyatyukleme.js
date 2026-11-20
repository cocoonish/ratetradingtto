// Kâğıt Fiyat Yükleme (tto/fiyatyukleme.py): the desk's daily price upload.  The user's own list of bonds (ISIN, the
// catalog's description, maturity) with a bid and an ask spread each - or the defaults -, BBG / İhale, the morning's
// auction text pasted, Hesapla: every bond at t0 (today's value date) with its two sides, every cell editable (a yield
// edited gives its price and the other way round, by the server's BIST conventions), Kaydet (txt): the desk's file
// "ISIN,pricebid,priceask,yieldbid,yieldask" (bills and zero coupons by their yields, the rest by their prices, the
// other two 0), downloaded and kept for a second download today.  An auction line the page cannot read is named once
// (desk-wide) and known from then on.
import { api } from '../api.js';
import { h, clear, toast, errorToast } from '../ui.js';
import { num, parseNumber } from '../format.js';

const isNum = (v) => typeof v === 'number' && isFinite(v);
const n3 = (v) => (isNum(v) ? num(v, 3, false) : '');
const day = (iso) => (iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4) : '');
const f3 = (v) => v.toFixed(3);                       // the file's figures: three decimals, a dot
const SIDES = [['bid', 'yield', 'fy-bid-y'], ['ask', 'yield', 'fy-ask-y'], ['bid', 'price', 'fy-bid-p'], ['ask', 'price', 'fy-ask-p']];

function panel(id, title, note) {
  const body = h('div', { class: 'body' });
  const el = h('section', { class: 'panel wide fy-panel', id }, h('header', null, h('h2', null, title)), body,
    note ? h('div', { class: 'note' }, note) : null);
  return { el, body };
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
    this.list = panel('fy-list', 'Kâğıt listesi',
      'Liste sizin: siz çıkarana kadar kalır. Getiriyle kote edilenler (sabit kuponlu, bono, kuponsuz): bid getiri = t0 + bid spread, ask getiri = t0 − ask spread (bp). '
      + 'Fiyatla kote edilenler (TLREF, FRN, TÜFE): bid fiyat = t0 − bid spread, ask fiyat = t0 + ask spread (fiyat puanı). Eurobond (USD / EUR, ISIN\'iyle '
      + 'eklenir): mod ne olursa olsun Bloomberg\'in mid\'inden; bid getiri = mid + bid spread, ask getiri = mid − ask spread (bp, kendi varsayılanı), fiyatlar '
      + 'Bloomberg\'in mid\'ine çapalı sokak kuralıyla. Satırın spread\'i boşsa varsayılan; eksi değer olur (skew).');
    this.sabit = panel('fy-sabit', 'Sabit fiyatlar', 'Bu kâğıtlar hesaplanmadan, girildiği gibi yüklenir ve siz değiştirene ya da çıkarana kadar kalır. Yalnız ISIN, '
      + 'bid ve offer gerekir (katalogda olmayan döviz DİBS de olur; vadesi ISIN\'den okunur). Değerler dosyaya yazıldığı birimde: bono ve kuponsuz getiri '
      + '(%, basit), diğerleri temiz fiyat. Aynı ISIN yeniden yapıştırılınca güncellenir. Listede de olan bir kâğıtta sabit fiyat geçerlidir. Hesaplanan bir '
      + 'satırı "Sabitle" ile buraya alabilirsiniz.');
    this.result_ = panel('fy-result', 'Fiyatlar · t0', 'Getiriler BIST basit getiri (%), fiyatlar t0 valöründe temiz. Her hücre düzenlenebilir: getiri değişince fiyatı, '
      + 'fiyat değişince getirisi aynı kurallarla yeniden hesaplanır. Dosyaya: bono / kuponsuz getiriyle, diğerleri fiyatla yazılır. Sabit fiyatlı satırdaki '
      + 'değişiklik yalnız bu Hesapla içindir.');
    this.file = panel('fy-file', 'Dosya (Kaydet\'te yazılacak satırlar)');
    this.labels = panel('fy-labels', 'Tanıtılan ihale etiketleri (masanın)');
    panels.append(this.ihale.el, this.list.el, this.sabit.el, this.result_.el, this.file.el, this.labels.el);
    this.host.appendChild(panels);
  }

  async load() {
    this.state = await api.get('/api/fiyat-yukleme');
    this.text.value = this.state.text || '';
    this.drawAll();
  }

  // The page holds the user's work (the text, the edits): nothing is fetched again on a new generation.
  async refresh() {}

  drawAll() {
    this.drawMode();
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
      this.state = await api.post('/api/fiyat-yukleme/ayar', { mode: m });
      this.result = null;
      this.drawMode();
      this.drawResult();
      this.drawFile();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ the list
  drawList() {
    const st = this.state || {};
    const body = clear(this.list.body);
    const add = h('div', { class: 'fy-add' });
    this.addText = h('textarea', { class: 'inp', id: 'fy-add-text', rows: '2', spellcheck: 'false', placeholder: 'ISIN ya da ISIN listesi (satır satır ya da virgülle)' });
    const addBtn = h('button', { class: 'btn', type: 'button', id: 'fy-add' }, 'Ekle');
    addBtn.addEventListener('click', () => this.addBonds(this.addText.value));
    add.append(this.addText, addBtn);
    body.appendChild(add);
    // the defaults: one setting each, for every bond without its own
    const d = st.defaults || {};
    const defs = h('div', { class: 'fy-defs', id: 'fy-defs' }, h('span', { class: 'muted' }, 'Varsayılan spread:'));
    this.defInputs = {};
    for (const [k, label] of [['yield_bid', 'Getiri bid (bp)'], ['yield_ask', 'Getiri ask (bp)'], ['price_bid', 'Fiyat bid'], ['price_ask', 'Fiyat ask'],
      ['euro_bid', 'Eurobond bid (bp)'], ['euro_ask', 'Eurobond ask (bp)']]) {
      const inp = h('input', { class: 'inp', id: 'fy-def-' + k.replace('_', '-'), value: num(d[k], k.startsWith('price') ? 3 : 1, false), size: '6', inputmode: 'decimal' });
      this.defInputs[k] = inp;
      defs.append(h('label', null, label + ' ', inp));
    }
    const defSave = h('button', { class: 'btn', type: 'button', id: 'fy-def-save' }, 'Kaydet');
    defSave.addEventListener('click', () => this.saveDefaults());
    defs.appendChild(defSave);
    body.appendChild(defs);
    const t = h('table', { class: 'plain fy', id: 'fy-list-table' });
    t.appendChild(h('tr', null, ...[['ISIN', 'l'], ['Kâğıt', 'l'], ['Açıklama', 'l'], ['Vade', ''], ['Tür', 'l'], ['Bid spread', ''], ['Ask spread', ''], ['Birim', 'l'], ['', '']]
      .map(([x, c]) => h('th', { class: c || null }, x))));
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
      tr.append(h('td', { class: 'l' }, r.isin), h('td', { class: 'l b' }, r.label || ''), h('td', { class: 'l fy-name' }, r.name || ''),
        h('td', null, day(r.maturity)), h('td', { class: 'l fy-kind' }, (r.kind_text || '') + (r.kind === 'euro' ? ' · ' + (r.ccy || '') : '')),
        spIn('bid'), spIn('ask'), h('td', { class: 'l muted' }, sp.unit === 'bp' ? (r.kind === 'euro' ? 'bp (BBG getirisi)' : 'bp (getiri)') : 'fiyat'), del);
      t.appendChild(tr);
    }
    if (!(st.list || []).length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '9' }, 'Liste boş: yukarıya ISIN yazıp Ekle')));
    body.appendChild(t);
  }

  async addBonds(text) {
    if (!String(text || '').trim()) { toast('ISIN yazın', 'err'); return; }
    try {
      const got = await api.post('/api/fiyat-yukleme/ekle', { isins: text });
      this.state = got;
      this.drawList();
      if (got.added.length) toast(got.added.length + ' kâğıt eklendi', 'ok');
      if (got.skipped.length) toast('Zaten listede: ' + got.skipped.join(', '));
      for (const r of got.refused || []) toast(r.isin + ': ' + r.text, 'err', 7000);
      if (got.added.length && this.addText) this.addText.value = '';
    } catch (err) { errorToast(err); }
  }

  async removeBond(isin) {
    try {
      this.state = await api.post('/api/fiyat-yukleme/cikar', { isin });
      this.drawList();
      if (this.result) {
        this.result.rows = this.result.rows.filter((r) => r.isin !== isin);
        this.drawResult();
        this.drawFile();
      }
    } catch (err) { errorToast(err); }
  }

  async saveSpread(isin, side, value) {
    try {
      this.state = await api.post('/api/fiyat-yukleme/ayar', { spreads: { [isin]: { [side]: value.trim() } } });
      this.drawList();
      this.markStale();
    } catch (err) { errorToast(err); this.drawList(); }
  }

  async saveDefaults() {
    const defaults = {};
    for (const [k, inp] of Object.entries(this.defInputs || {})) defaults[k] = inp.value.trim();
    try {
      this.state = await api.post('/api/fiyat-yukleme/ayar', { defaults });
      this.drawList();
      this.markStale();
      toast('Varsayılan spread kaydedildi', 'ok');
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ fixed prices ("Sabit fiyat")
  drawSabit() {
    const st = this.state || {};
    const body = clear(this.sabit.body);
    // Excel's rows pasted: ISIN, bid, offer (the cells between - an empty column, a yield, a stock - skipped by the server)
    const text = h('textarea', { class: 'inp fy-sabit-text', id: 'fy-sabit-text', rows: '4', spellcheck: 'false',
      placeholder: 'Excel\'den ISIN, Bid ve Offer\'ı kopyalayıp yapıştırın - her satır bir kâğıt (aradaki boş sütun, getiri ve stok sütunları atlanır).\n'
        + 'TRT191127F19\t99.483\t\t99.726' });
    const go = h('button', { class: 'btn', type: 'button', id: 'fy-sabit-yapistir' }, 'Ekle / Güncelle');
    go.addEventListener('click', () => this.pasteFixed(text.value));
    body.appendChild(h('div', { class: 'fy-add' }, text, go));
    this.sabitText = text;
    const rep = h('div', { class: 'fy-sabit-rapor', id: 'fy-sabit-rapor' });
    const p = this.lastPaste;
    if (p) {
      rep.appendChild(h('div', { class: 'muted' }, p.added.length + ' kâğıt eklendi · ' + p.updated.length + ' güncellendi · ' + p.bad.length
        + ' satır okunamadı' + (p.ignored ? ' · ' + p.ignored + ' satır yok sayıldı (başlık, grup adı)' : '')));
      for (const b of p.bad) rep.appendChild(h('div', { class: 'fy-sabit-bad' }, 'Satır ' + b.n + ': ' + b.text + ' - ' + b.why));
    }
    body.appendChild(rep);
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
  }

  async pasteFixed(text) {
    if (!String(text || '').trim()) { toast('Excel\'den ISIN, bid ve offer\'ı yapıştırın', 'err'); return; }
    try {
      const got = await api.post('/api/fiyat-yukleme/sabit-yapistir', { text });
      this.state = got;
      this.lastPaste = got.pasted;
      this.drawSabit();
      if (got.pasted.bad.length && this.sabitText) this.sabitText.value = text;      // (the lines left to fix stay)
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
      this.state = got;
      this.drawSabit();
      this.markStale();
      toast(isin + ': sabit fiyat kaydedildi', 'ok');
      if (got.crossed) toast(isin + ': bid ask\'ten iyi (ters kotasyon)', 'err', 6000);
    } catch (err) { errorToast(err); this.drawSabit(); }
  }

  async removeFixed(isin) {
    try {
      this.state = await api.post('/api/fiyat-yukleme/sabit-sil', { isin });
      this.drawSabit();
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

  markStale() {
    const info = document.getElementById('fy-result-info');
    if (this.result && info) info.textContent = 'Spread değişti: yeniden Hesapla';
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
        ? 'Bloomberg\'in son işleminden (DİBS RV; listede olmayanlar için tek seferlik istek, kâğıt başına 2 hit)' : 'yapıştırılan ihale fiyatlarından') + ' t0\'da fiyatlanır.'));
      return;
    }
    const parts = [(res.mode === 'bbg' ? 'BBG' : 'İhale') + ' · t0 ' + day(res.t0) + ' · ' + (res.time || '')];
    if (res.bbg) {
      const b = res.bbg;
      parts.push(b.why ? 'Bloomberg: ' + b.why : 'Bloomberg\'e ' + b.asked + ' kâğıt soruldu (' + b.hits + ' hit), ' + b.cached + ' son 5 dakikadan');
      parts.push('DİBS RV\'den ' + b.trading);
    }
    if (res.euro) {
      const e = res.euro;
      parts.push(e.why ? 'Eurobond: ' + e.why : 'Eurobond mid\'i: ' + e.asked + ' soruldu (' + e.hits + ' hit), ' + e.cached + ' son 5 dakikadan'
        + (e.sides ? ', ' + e.sides + ' kâğıtta PX_MID boş: bid / ask\'ın ortası' : ''));
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
    tr.append(h('td', { class: 'l b' }, r.label || ''), h('td', { class: 'l' }, r.isin), h('td', { class: 'l fy-name' }, r.name || ''), h('td', null, day(r.maturity)),
      h('td', { class: 'fy-t0-y', title: midTip }, n3(t0.yield)), h('td', { class: 'fy-t0-p', title: midTip }, n3(t0.price)), ...cells,
      h('td', { class: 'l fy-write' }, r.write === 'yield' ? 'getiri' : 'fiyat'), act,
      // a bond priced off the curve (no trade, no auction): said first, so the desk sees it before saving
      h('td', { class: 'l fy-how', title: how }, r.curve ? h('b', { class: 'fy-curve-mark', title: 'Başka fiyatı yoktu: Kâğıt Fiyatlama\'nın eğri fiyatı ('
        + r.curve.label + ') ve satırın spreadleri' }, 'eğri fiyatı') : '', r.curve ? ' · ' : '', how));
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
      if (old) old.replaceWith(this.rowEl(r));
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
