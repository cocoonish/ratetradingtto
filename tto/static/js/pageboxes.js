// The kinds of boxes of the dashboard's own pages (pagebox.js is their frame), each drawing what its page draws for it -
// the same rows from the same functions - with the choices its page has:
//   quant-signals   Sinyaller's live list (its family / asset filter); a click opens the signal's card over the box, or
//                   on the Sinyaller page
//   viop-levels     VİOP's order levels of a contract, or of the front one ("ön vade": it rolls with the front)
//   viop-contracts  VİOP's contracts with their live implied rates
//   broker-board    Broker Chat's board: the best bid / ask of every instrument (product, instruments, every house's own)
//   watch-list      one of İzleme's lists: the watch list, the alarms, today's alarms that fired
//   wirp            TCMB WIRP's meeting table (TCMB or the Fed)
//   fx-summary      FX's pair summary (carry, expected drift, buffer, verdict)
// Registered with the launchpad's kinds of items (boxes.js BOX_TYPES); the server checks them (tto/layout.py ITEM_TYPES).
import { api } from './api.js';
import { h, clear, modal, toast, errorToast } from './ui.js';
import { plainData } from './grid.js';
import { isoToTr, num } from './format.js';
import { BOX_TYPES } from './boxes.js';
import { OwnBox } from './pagebox.js';
import { SignalChart, signalRows, SIGNAL_HEAD, isNum } from './pages/quantbase.js';
import { CONTRACT_HEAD, contractRows, levelsTitle, drawLevels } from './pages/quantviop.js';
import { FX_SUMMARY_HEAD, fxSummaryRows } from './pages/quantviews.js';
import { wirpHead, wirpRows } from './pages/quantpath.js';
import { boardTable, whoHidden } from './pages/broker.js';
import { OP, KIND_TEXT, changeText, spark, band, savedDays } from './pages/watch.js';

const mark = (on) => (on ? '✓ ' : '    ');

/** A signal's (or a monitor's) card over the box: the Sinyaller page's card - the sentence, the series with its bands,
 *  entry / target / stop - without the page's element ids; "Sinyaller sayfasında aç" opens it there. */
async function openCard(box, sid) {
  let chart = null;
  const m = modal({ title: 'Sinyal', width: 1040, onClose: () => { if (chart) chart.destroy(); } });
  m.box.classList.add('qcard', 'quantpage');                // (the card's own look: the Sinyaller page's)
  chart = new SignalChart(m.body, { ids: false });
  chart.loading('');
  const go = h('button', { class: 'btn', type: 'button', title: 'Sinyaller sayfasında, kartıyla' }, 'Sinyaller sayfasında aç');
  go.addEventListener('click', () => { m.close(); box.goTo('quant', 'sig:' + sid); });
  m.foot.append(go, h('button', { class: 'btn primary', type: 'button', onclick: () => m.close() }, 'Kapat'));
  try {
    const d = await api.get('/api/quant/signal', { id: sid });
    if (!m.el.isConnected) return;
    chart.show(d);
    m.box.querySelector('header h2').textContent = chart.titleEl.textContent || 'Sinyal';
  } catch (err) { m.close(); errorToast(err); }
}

/** The frame with where a box goes to: its page (a window of its own opens it in the main window). */
class PageBox extends OwnBox {
  goTo(page, panel) {
    if (this.ctx.gotoSource) this.ctx.gotoSource(page, panel || null);
    else this.ctx.goto(page, panel || null);
  }

  optionItems() {
    return [];
  }
}

// ---------------------------------------------------------------------- quant (the results' version moves them)
class SignalsBox extends PageBox {
  constructor(item, opts) {
    super(item, opts);
    this.follows = 'quant';
    this.page = 'quant';
    this.where = 'Quant › Sinyaller';
    this.start();
  }

  part(it) {
    return { path: '/api/quant/box', params: { of: 'signals', family: it.family || undefined, asset: it.asset || undefined, group: it.group || undefined } };
  }

  titleText() {
    const fam = this.item.family ? ((this.data && this.data.family_label) || this.item.family) : '';
    return 'Sinyaller' + (this.item.group ? ' · ' + this.item.group : '') + (fam ? ' · ' + fam : '') + (this.item.asset ? ' · ' + this.item.asset : '');
  }

  paint(d) {
    if (!d.ready) { this.notReady(d); return; }
    const sig = d.signals || [];
    if (!sig.length) {
      this.empty('Şu an eşiği geçen sinyal yok (giriş |z| ≥ ' + num(d.entry_z || 2, 1) + ')' + (this.item.family || this.item.asset || this.item.group ? ' – süzgeçle' : '') + '.');
      return;
    }
    this.ids = sig.map((s) => s.id);                // (read at the click: the grid's handler stays while its rows change)
    // (the page's list: by group, a gate's "düşük güven" lines grey after the confident ones, the reason last)
    const rows = signalRows(sig, { rank: true, group: true }).map((row, i) => {
      if (sig[i].gated) for (const c of row) if (c && typeof c === 'object') c.cls = ((c.cls || '') + ' soft').trim();
      return row;
    });
    this.showGrid(plainData(['#', 'Grup'].concat(SIGNAL_HEAD, ['Bileşik / neden', 'Saat']), rows), 'quant/signals',
      (i) => this.open(this.ids[i]), JSON.stringify(this.ids));
  }

  open(sid) {
    if (!sid) return;
    if (this.item.open === 'page') this.goTo('quant', 'sig:' + sid);
    else openCard(this, sid);
  }

  optionItems() {
    return [{ header: 'Sinyale tıklayınca' },
      { label: mark(this.item.open !== 'page') + 'Kartı burada aç', action: () => this.change({ open: 'card' }) },
      { label: mark(this.item.open === 'page') + 'Sinyaller sayfasında aç', action: () => this.change({ open: 'page' }) },
      { sep: true },
      { label: 'Grup, aile ve varlık…' + (this.item.family || this.item.asset || this.item.group ? ' (süzgeç var)' : ''), action: () => this.pickFilter() }];
  }

  /** The page's filters: a group, a family, an asset (none: all). */
  pickFilter() {
    const d = this.data || {};
    const m = modal({ title: 'Sinyaller · süzgeç', width: 420 });
    const group = h('select', { class: 'inp', style: { width: '100%' } }, h('option', { value: '' }, 'Tümü'),
      (d.groups || []).map((g) => h('option', { value: g }, g)));
    const fam = h('select', { class: 'inp', style: { width: '100%' } }, h('option', { value: '' }, 'Tümü'),
      (d.families || []).map((f) => h('option', { value: f.id }, f.label)));
    const asset = h('select', { class: 'inp', style: { width: '100%' } }, h('option', { value: '' }, 'Tümü'),
      (d.assets || []).map((a) => h('option', { value: a }, a)));
    group.value = this.item.group || '';
    fam.value = this.item.family || '';
    asset.value = this.item.asset || '';
    m.body.append(h('div', { class: 'field' }, h('label', null, 'Grup'), group), h('div', { class: 'field' }, h('label', null, 'Aile'), fam),
      h('div', { class: 'field' }, h('label', null, 'Varlık'), asset));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: () => {
      m.close();
      this.change({ group: group.value || null, family: fam.value || null, asset: asset.value || null });
    } }, 'Kaydet'));
  }
}

/** VİOP's part: the contracts now, with their order levels (one request for both boxes). */
class ViopBox extends PageBox {
  constructor(item, opts) {
    super(item, opts);
    this.follows = 'quant';
    this.page = 'quant-viop';
    this.where = 'Quant › VİOP';
  }

  part() {
    return { path: '/api/quant/box', params: { of: 'viop' } };
  }

  /** In replay there is no history of the contracts: no fair value, no levels (the box says why). */
  replayNote(d) {
    this.say(d.mode === 'replay' ? 'Kayıtlı veri modu: kontratların Bloomberg geçmişi yok – adil değer ve seviyeler canlı modda.' : '');
  }
}

class ViopLevelsBox extends ViopBox {
  constructor(item, opts) {
    super(item, opts);
    this.start();
  }

  choice() {
    return this.item.contract || 'front';
  }

  /** The contract shown: the one chosen, or the front one (the first listed: an expired contract leaves the list). */
  contract() {
    const rows = (this.data && this.data.rows) || [];
    const c = this.choice();
    return c === 'front' ? rows[0] || null : rows.find((r) => r.ticker === c) || null;
  }

  titleText() {
    const r = this.data && this.data.ready ? this.contract() : null;
    const front = this.choice() === 'front';
    if (r) return levelsTitle(r) + (front ? ' · ön vade' : '');
    return 'VİOP emir seviyeleri · ' + (front ? 'ön vade' : this.choice());
  }

  paint(d) {
    if (!d.ready) { this.notReady(d); return; }
    const r = this.contract();
    this.replayNote(d);
    if (!r) {
      this.empty((d.rows || []).length ? this.choice() + ' artık listede yok (vadesi geçmiş olabilir): ⋯ → "Ön vade" ya da başka bir kontrat'
        : (d.why || 'Canlı VİOP kotası yok'));
      return;
    }
    this.grid = null;
    const host = h('div', { class: 'qcols' });
    drawLevels(host, r);
    clear(this.body);
    this.body.appendChild(host);
  }

  optionItems() {
    const rows = (this.data && this.data.rows) || [];
    const c = this.choice();
    return [{ header: 'Kontrat' }, { label: mark(c === 'front') + 'Ön vade (vadesi dolunca sonrakine geçer)', action: () => this.change({ contract: 'front' }) }]
      .concat(rows.map((r) => ({ label: mark(c === r.ticker) + r.name + ' · ' + r.ticker, action: () => this.change({ contract: r.ticker }) })));
  }
}

class ViopContractsBox extends ViopBox {
  constructor(item, opts) {
    super(item, opts);
    this.start();
  }

  titleText() {
    return 'VİOP kontratları · canlı ima faizler';
  }

  paint(d) {
    if (!d.ready) { this.notReady(d); return; }
    this.replayNote(d);
    const rows = d.rows || [];
    if (!rows.length) { this.empty(d.why || 'Canlı VİOP kotası yok'); return; }
    this.sids = rows.map((r) => r.sid || null);     // (read at the click: the grid's handler stays while its rows change)
    this.showGrid(plainData(CONTRACT_HEAD, contractRows(rows, null, d.entry_z || 2)), 'quant/viop/contracts',
      (i) => { if (this.sids[i]) openCard(this, this.sids[i]); }, JSON.stringify(rows.map((r) => r.ticker)));
  }
}

class WirpBox extends PageBox {
  constructor(item, opts) {
    super(item, opts);
    this.follows = 'quant';
    this.page = 'quant-wirp';
    this.where = 'Quant › TCMB WIRP';
    this.start();
  }

  part() {
    return { path: '/api/quant/box', params: { of: 'wirp' } };
  }

  bank() {
    return this.item.bank === 'usd' ? 'usd' : 'try';
  }

  titleText() {
    const b = this.data && this.data.ready ? (this.data.banks || {})[this.bank()] : null;
    return 'WIRP · ' + (this.bank() === 'usd' ? 'Fed' : 'TCMB') + ' · toplantı başına' + (b && b.ok ? ' · ' + isoToTr(b.day) + (b.live ? ' ●' : '') : '');
  }

  paint(d) {
    if (!d.ready) { this.notReady(d); return; }
    const b = (d.banks || {})[this.bank()] || {};
    if (!b.ok || !(b.rows || []).length) { this.empty(b.why || 'Patika yok'); return; }
    this.showGrid(plainData(wirpHead(this.bank()), wirpRows(b)), 'quant/wirp/table', null, JSON.stringify(b.rows.map((r) => r.meeting)));
    const pol = b.policy || {};
    this.say(isNum(pol.rate) ? 'Politika faizi %' + num(pol.rate, 2) + (pol.source ? ' (' + pol.source + ')' : '') : '');
  }

  optionItems() {
    return [{ header: 'Merkez bankası' },
      { label: mark(this.bank() === 'try') + 'TCMB', action: () => this.change({ bank: 'try' }) },
      { label: mark(this.bank() === 'usd') + 'Fed', action: () => this.change({ bank: 'usd' }) }];
  }
}

class FxSummaryBox extends PageBox {
  constructor(item, opts) {
    super(item, opts);
    this.follows = 'quant';
    this.page = 'quant-fx';
    this.where = 'Quant › FX';
    this.start();
  }

  part() {
    return { path: '/api/quant/box', params: { of: 'fxsum' } };
  }

  titleText() {
    return 'Parite özeti · carry, beklenen kayma, tampon, karar';
  }

  paint(d) {
    if (!d.ready) { this.notReady(d); return; }
    const fs = d.fxsum || {};
    const rows = fxSummaryRows(fs);
    if (!rows.length) { this.empty(fs.why || 'Spot / forward tarihçesi yok'); return; }
    this.showGrid(plainData(FX_SUMMARY_HEAD, rows), 'quant/fx/summary', null, JSON.stringify((fs.rows || []).map((r) => r.pair)));
  }
}

// ---------------------------------------------------------------------- Broker Chat's changes, the generation
const PRODUCTS = [['all', 'Tümü'], ['OIS', 'OIS'], ['XCCY', 'XCCY'], ['FX', 'FX swap'], ['DIBS', 'DİBS']];
const BOARD_AGAIN_MS = 20000;            // the ages (and the model) move while nothing is said: read again now and then, as the page

class BrokerBoardBox extends PageBox {
  constructor(item, opts) {
    super(item, opts);
    this.follows = 'chat';                        // (Broker Chat's own changes - not every generation of the market)
    this.page = 'broker';
    this.where = 'Broker Chat';
    this.start();
  }

  part() {
    return { path: '/api/broker', params: { part: 'board' } };
  }

  titleText() {
    const p = PRODUCTS.find(([v]) => v === (this.item.product || 'all'));
    const n = (this.item.keys || []).length;
    return 'Broker Chat tahtası' + (p && p[0] !== 'all' ? ' · ' + p[1] : '') + (n ? ' · ' + n + ' enstrüman' : '');
  }

  paint(d) {
    const t = boardTable(d, { product: this.item.product || 'all', keys: this.item.keys, brokers: !!this.item.brokers, everyHouse: whoHidden() });
    if (!t.lines.length) {
      this.empty(d.board.length ? 'Seçilen ürün / enstrümanlarda kota yok' : 'Henüz kota yok – chat Broker Chat sayfasında yapıştırılır');
    } else {
      this.showGrid(plainData(t.header, t.lines), 'broker/board', null, t.same);
    }
    if (d.live && !this.timer) this.timer = setInterval(() => { if (this.wanted()) this.refreshOwn(true); }, BOARD_AGAIN_MS);
    else if (!d.live && this.timer) { clearInterval(this.timer); this.timer = null; }
  }

  optionItems() {
    const p = this.item.product || 'all';
    return [{ header: 'Ürün' }].concat(PRODUCTS.map(([v, label]) => ({ label: mark(p === v) + label, action: () => this.change({ product: v }) })), [
      { label: 'Enstrümanlar…' + ((this.item.keys || []).length ? ' (' + this.item.keys.length + ' seçili)' : ''), action: () => this.pickKeys() },
      { check: true, on: !!this.item.brokers, label: 'Her broker\'ın kendi kotası', sub: 'enstrümanın altında',
        action: (on) => this.change({ brokers: on || null }) }]);
  }

  /** The instruments kept: today's board to pick from (and the ones picked that have no quote today), ticked as now. */
  pickKeys() {
    const board = ((this.data || {}).board) || [];
    const now = this.item.keys || [];
    const known = new Map(board.map((r) => [r.key, (r.product === 'DIBS' ? 'DİBS' : r.product) + ' · ' + r.label]));
    for (const k of now) if (!known.has(k)) known.set(k, k + ' (bugün kotası yok)');
    if (!known.size) { toast('Tahtada henüz enstrüman yok', 'err'); return; }
    const m = modal({ title: 'Broker Chat tahtası · enstrümanlar', width: 460 });
    m.box.classList.add('lp-picker');
    const boxes = [];
    const list = h('div', { class: 'lp-pick-list' });
    for (const [k, label] of known) {
      const b = h('input', { type: 'checkbox' });
      b.checked = !now.length || now.includes(k);
      b.dataset.key = k;
      boxes.push(b);
      list.appendChild(h('label', { class: 'lp-pick' }, b, h('span', { class: 't' }, label)));
    }
    const all = (on) => () => { for (const b of boxes) b.checked = on; };
    m.body.append(h('div', { class: 'lp-pick-head' }, h('b', null, 'Enstrümanlar'),
      h('button', { class: 'btn sm', type: 'button', onclick: all(true) }, 'Tümü'), h('button', { class: 'btn sm', type: 'button', onclick: all(false) }, 'Hiçbiri')),
    h('div', { class: 'muted', style: { fontSize: '11.5px', margin: '0 0 6px' } }, 'Hepsi seçiliyken sonradan gelen enstrümanlar da görünür.'), list);
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: () => {
      const on = boxes.filter((b) => b.checked).map((b) => b.dataset.key);
      if (!on.length) { toast('En az bir enstrüman seçin', 'err'); return; }
      m.close();
      this.change({ keys: on.length === boxes.length && board.length === boxes.length ? null : on });
    } }, 'Kaydet'));
  }
}

const LISTS = { items: ['İzleme listesi', 'watch-list'], alarms: ['Alarmlar', 'watch-alarms'], fired: ['Bugün çalan alarmlar', 'watch-fired'] };

class WatchListBox extends PageBox {
  constructor(item, opts) {
    super(item, opts);
    this.follows = 'gen';
    this.page = 'watch';
    this.where = 'İzleme · Alarmlar';
    this.start();
  }

  list() {
    return LISTS[this.item.list] ? this.item.list : 'items';
  }

  /** (its panel on the page: "Sayfasına git" brings it into view) */
  get panel() {
    return LISTS[this.list()][1];
  }

  part(it) {
    const list = LISTS[it.list] ? it.list : 'items';
    return { path: '/api/watch', params: { part: list, days: list === 'items' ? savedDays() : undefined } };
  }

  titleText() {
    return LISTS[this.list()][0];
  }

  paint(d) {
    const list = this.list();
    this.grid = null;
    const rows = d[list] || [];
    if (!rows.length) {
      this.empty(list === 'items' ? 'İzleme listesi boş: kalemler İzleme sayfasında eklenir (ya da bir hücreye sağ tık → "İzlemeye ekle").'
        : list === 'alarms' ? 'Alarm yok: İzleme sayfasında ya da bir hücreye sağ tıklayıp "Alarm kur…".' : 'Bugün çalan alarm yok.');
      return;
    }
    const t = h('table', { class: 'plain watch' });
    const head = (cols, left) => t.appendChild(h('tr', null, ...cols.map((x, i) => h('th', { class: left.includes(i) ? 'l' : '' }, x))));
    const cls = (v) => (isNum(v) && Math.abs(v) > 1e-9 ? (v > 0 ? 'pos' : 'neg') : '');
    if (list === 'items') {
      head(['Ad', 'Şimdi', 'Açılış', 'Gün', 'Düşük', 'Yüksek', 'Gün içi', 'z (' + (d.days || 60) + 'g)', 'Bant', 'Referans', 'Ref\'ten', 'Son hareket'], [0, 6, 8]);
      for (const it of rows) {
        const kind = (it.subject && it.subject.kind) || 'cell';
        const z = it.z || {};
        t.appendChild(h('tr', null,
          h('td', { class: 'l name', title: (KIND_TEXT[kind] || kind) + ' · ' + it.what + (it.detail ? ' · ' + it.detail : '') }, it.label,
            !isNum(it.value) && it.detail ? h('span', { class: 'sub' }, it.detail) : null),
          h('td', { class: 'now' }, it.now || ''), h('td', null, it.open_text || ''), h('td', { class: cls(it.change) }, changeText(it.change, it)),
          h('td', null, it.low_text || ''), h('td', null, it.high_text || ''), h('td', { class: 'l' }, spark(it.path, it.open)),
          h('td', { class: 'z' + (isNum(z.z) && Math.abs(z.z) >= 2 ? ' far' : '') }, isNum(z.z) ? z.z_text : '–'), h('td', { class: 'l' }, band(z, it.value)),
          h('td', null, it.base_text || ''), h('td', { class: cls(it.since_base) }, changeText(it.since_base, it)), h('td', { class: 'muted' }, it.moved || '')));
      }
    } else if (list === 'alarms') {
      head(['Ad', 'Koşul', 'Şimdi', 'Hareket / z', 'Uzaklık', 'Durum', 'Not'], [0, 1, 5, 6]);
      for (const a of rows) {
        const state = a.active ? h('span', { class: 'pill neu' }, 'bekliyor')
          : h('span', { class: 'pill warn', title: 'Değer: ' + (a.fired_text || '') }, 'çaldı · ' + (a.fired_at || '').slice(11));
        t.appendChild(h('tr', { class: a.active ? '' : 'fired' }, h('td', { class: 'l', title: a.what + (a.detail ? ' · ' + a.detail : '') }, a.label),
          h('td', { class: 'l cond' }, a.condition || ((OP[a.op] || a.op) + ' ' + (a.level_text || ''))), h('td', null, a.now_text || ''),
          h('td', null, a.mode && a.mode !== 'level' ? (a.measure_text || '–') : ''), h('td', { title: 'Koşulun sağlanmasına kalan' }, a.distance_text || ''),
          h('td', { class: 'l' }, state), h('td', { class: 'l muted' }, a.note || '')));
      }
    } else {
      head(['Saat', 'Ad', 'Koşul', 'Değer', 'Hareket / z', 'Not'], [0, 1, 2, 5]);
      for (const e of rows.slice().reverse()) {
        t.appendChild(h('tr', null, h('td', { class: 'l' }, e.time), h('td', { class: 'l' }, e.label),
          h('td', { class: 'l' }, e.condition || ((OP[e.op] || e.op) + ' ' + (e.level_text || ''))), h('td', null, e.value_text || ''),
          h('td', null, e.mode && e.mode !== 'level' ? (e.measure_text || '') : ''), h('td', { class: 'l muted' }, e.note || '')));
      }
    }
    clear(this.body);
    this.body.appendChild(t);
  }

  optionItems() {
    const list = this.list();
    return [{ header: 'Liste' }].concat(Object.entries(LISTS).map(([k, [label]]) => ({ label: mark(list === k) + label, action: () => this.change({ list: k }) })));
  }
}

Object.assign(BOX_TYPES, {
  'quant-signals': SignalsBox,
  'viop-levels': ViopLevelsBox,
  'viop-contracts': ViopContractsBox,
  'broker-board': BrokerBoardBox,
  'watch-list': WatchListBox,
  wirp: WirpBox,
  'fx-summary': FxSummaryBox,
});
