// Kâğıt Fiyatlama (tto/kagitfiyat.py): every fixed coupon bond and bill of the trading list with one fair level - the
// neighbours' curve (Nelson-Siegel of the other bonds) and OIS, each plus the bond's spread at the last close, weighted by
// maturity -, the projected yield and price at the horizon chosen (Öngörülen: the model the desk's history chose for the
// bond's bucket and the horizon, with its record), the fair values DİBS Trading shows on its two ASW curves (OIS'e göre,
// FX swap'a göre), a quote around the fair, the good levels (fair ± 2σ) with their backtest, the market now against them
// and, under each bond, how the price and the projection were built.  The quote's width is the administrators' (typed
// here, logged).
import { api } from '../api.js';
import { h, clear, toast, errorToast } from '../ui.js';
import { num } from '../format.js';
import { bondCardLinks } from '../bonds.js';
import { isNum, yld, px, bp, sig, day, hitText, hitTip, sigmaTip, quoteText, marketTip, horizonOf, horizonSwitch, projAt, projTip, tl,
  modelShort, aswTip } from '../kagitblock.js';

const COLS = 28;                                       // the details' table's columns (the how-line and a reason span them)
const WHY_SPAN = 9;                                    // a bond not priced: its reason over the fair and the projection…
const REST_SPAN = 11;                                  // …and nothing over the quote, the levels, the market and the context
const ASW = [['ois', "OIS'e göre"], ['fx', "FX swap'a göre"]];
const MAIN_COLS = 14;                                  // the main table's columns (a bond's details span them)
const HEAD_LINE = 'Fiyatı olmayan kâğıtlara eğriden fiyat: masanın listesindeki her sabit kuponlu, bono ve kuponsuz kâğıt. Fiyat: bugün '
  + 'piyasa fiyatı varsa o (piyasa: iki taraflı kotanın ortası ya da bugünkü son işlem); yoksa eğri + kâğıdın son kapanıştaki eğriye farkı '
  + '(eğri + son fark: masanın geçmişinde en iyi tahmin); geçmişi yoksa eğri + aynı vade kovasında bugün piyasa fiyatlı akranlarının (bono / '
  + 'kuponsuz bir arada, sabit kuponlu ayrı) eğriye farklarının medyanı (eğri + akran farkı); akranı da yoksa eğri. Eğri, vade kovasına göre: '
  + '1 yıla kadar %75 OIS sıfır faizi + %25 Nelson-Siegel, 1–5 yıl Nelson-Siegel, 5 yıl üstü %75 Nelson-Siegel + %25 OIS (adil getirinin '
  + 'ağırlıkları); Nelson-Siegel fiyatı olan kâğıtlara şimdi uydurulur, kâğıdın kendi nakit akışlarında (uydurmadaki kâğıt kendisi dışarıda). '
  + 'Getiriler BIST bileşik, fiyat valörde temiz. ▸ ayrıntılar: adil, kota, iyi seviyeler, σ, geri test, öngörülen, OIS\'e / FX swap\'a göre.';

function panel(id, title, note) {
  const body = h('div', { class: 'body' });
  const el = h('section', { class: 'panel wide', id }, h('header', null, h('h2', null, title)), body,
    note ? h('div', { class: 'note' }, note) : null);
  return { el, body };
}

function cell(text, opts = {}) {
  return h('td', { class: opts.cls || null, title: opts.tip || null, colspan: opts.span ? String(opts.span) : null }, text);
}

export class KagitFiyatPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.timer = null;
    this.open = new Set();                               // the bonds whose details are open (kept across a refresh)
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools kf-tools', id: 'kf-tools' });
    this.info = h('span', { class: 'muted', id: 'kf-info' });
    this.ufuk = h('span', { id: 'kf-ufuk' });
    tools.append(h('b', null, 'Kâğıt Fiyatlama'), this.info, h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Öngörülen ufku'), this.ufuk,
      h('span', { class: 'muted', id: 'kf-time' }));
    this.host.appendChild(tools);
    this.host.appendChild(h('p', { class: 'kf-head-line', id: 'kf-head-line' }, HEAD_LINE));
    this.rules = h('div', { class: 'chips kf-rules', id: 'kf-rules' });
    this.host.appendChild(this.rules);
    const panels = h('div', { class: 'panels' });
    this.table = panel('kf-panel', 'Masanın kâğıtları · piyasa, eğri, fiyat (▸ ayrıntılar: adil, öngörülen, OIS ve FX swap\'a göre, kotan, iyi seviyeler)',
      'Ayrıntılar (▸): Adil getiri: tabanlar (komşu eğri: trading listesinin diğer sabit kuponlularına uydurulan Nelson-Siegel eğrisi, kâğıt dışarıda; OIS: '
      + 'TRY OIS Bootstrap sıfır faizi vadede) + kâğıdın son kapanıştaki farkı, vadeye göre ağırlıklı. Öngörülen: seçilen ufukta (1 hafta / 2 hafta / '
      + '1 ay) ulaşması beklenen getiri ve fiyat - kovanın ve ufkun masanın geçmişinde seçilen modeliyle; hiçbir model "değişmez"i yenemediyse eğri ve '
      + 'fark değişmezse (söylenir). OIS\'e göre / FX swap\'a göre: DİBS Trading\'in aynı adlı sütunlarındaki adil getiri ve fiyat. Getiriler BIST bileşik '
      + '(basit yanında), fiyat DİBS RV valöründe temiz (öngörülen: ufkun valöründe). Al: getiri adil + 2σ ya da üstünde (ucuz); Sat: adil − 2σ ya da '
      + 'altında (pahalı); ±1σ gürültü. σ kâğıdın son 60 kapanıştaki sonraki-gün hatası, kovanın tabanıyla. Piyasa: Broker Chat tahtasının en iyi taze '
      + 'bid / offer\'ı ve Bloomberg canlı bid / ask (DİBS RV), adilden σ cinsinden. Hücrelerin üzerine gelince hesabı; ▸ kâğıt kartı.');
    this.widths = panel('kf-widths', 'Kotasyon genişliği (bp, bid ile ask arası)');
    panels.append(this.table.el, this.widths.el);
    this.host.appendChild(panels);
    bondCardLinks(this.ctx, this.table.body);
  }

  async load() { await this.refresh(); }

  async refresh() {
    const d = await api.get('/api/kagit-fiyat');
    this.data = d;
    if (!d.ok) {
      clear(this.table.body).appendChild(h('div', { class: 'empty' }, d.why || 'Veri yok'));
      return;
    }
    this.hz = horizonOf(d.projection);
    this.drawInfo(d);
    this.drawHorizon(d);
    this.drawWidths(d);
  }

  /** The horizon switch and what follows it: the rules' line and the table (drawn again from the answer kept). */
  drawHorizon(d) {
    clear(this.ufuk).appendChild(horizonSwitch(d.projection, this.hz, (x) => { this.hz = x; this.drawHorizon(this.data); }, 'kf-ufuk-'));
    this.drawRules(d);
    this.drawTable(d);
  }

  drawInfo(d) {
    const hi = d.history || {};
    const parts = [];
    if (hi.days) {
      parts.push('Geçmiş: ' + hi.days + ' kapanış (' + day(hi.first) + ' – ' + day(hi.last) + ')');
      if (hi.tau) parts.push('komşu eğri ' + hi.tau.model + ', τ ' + num(hi.tau.tau1, 2, false) + ' (' + day(hi.tau_day) + ' kapanışında arandı, sabit)');
      parts.push('OIS eğrisi ' + (hi.ois_days || 0) + ' günde');
    } else {
      parts.push('Geçmiş kapanış yok' + (hi.why ? ': ' + hi.why : ''));
    }
    const f = d.fit || {};
    if (f.ok) parts.push('şimdi: ' + f.n_fit + ' sabit kuponlu, birini dışarıda bırakarak');
    else if (f.why) parts.push('şimdi komşu eğri yok: ' + f.why);
    this.info.textContent = ' · ' + parts.join(' · ');
    this.info.title = isNum(hi.ms) ? 'Geçmişin hesabı ' + num(hi.ms / 1000, 1, false) + ' sn (' + (hi.built || '') + '); her tarihçe değişiminde yalnız değişen günler' : '';
    const t = document.getElementById('kf-time');
    if (t) t.textContent = d.time || '';
  }

  drawRules(d) {
    const r = d.rules || {};
    const w = r.weights || {};
    const pctOf = (x) => '%' + Math.round(x * 100);
    const text = (k) => Object.entries(w[k] || {}).filter(([, x]) => x > 0)
      .map(([b, x]) => pctOf(x) + ' ' + (b === 'nbr' ? 'komşu eğri' : 'OIS')).join(' + ');
    clear(this.rules).appendChild(h('span', { class: 'lbl' }, 'Kural'));
    for (const b of r.buckets || []) {
      this.rules.appendChild(h('span', { class: 'chip', title: 'σ tabanı ' + num((r.floor || {})[b.key], 0) + ' bp' },
        b.text + ': ', h('b', null, text(b.key)), ' · σ ≥ ' + num((r.floor || {})[b.key], 0) + ' bp'));
    }
    this.rules.appendChild(h('span', { class: 'chip' }, 'İyi seviye ±' + (r.band || 2) + 'σ · gürültü ±' + (r.noise || 1) + 'σ'));
    // Öngörülen: each bucket's model at the horizon chosen (the desk's history's choice), and where none beat "no change"
    const pj = d.projection || {};
    const table = pj.table || {};
    const hzText = ((pj.horizons || []).find((x) => x.h === this.hz) || {}).text || '';
    const models = (r.buckets || []).map((b) => {
      const rec = (table[b.key] || {})[String(this.hz)];
      if (!rec) return '';
      return b.text + ' ' + (rec.beat ? rec.model + '/' + rec.window : 'eğri+fark sabit');
    }).filter(Boolean);
    this.rules.appendChild(h('span', { class: 'chip', id: 'kf-proj-rules',
      title: 'Kova ve ufuk başına, masanın geçmişinde (' + (pj.source || '') + ') "değişmez"i RMSE\'de en az %' + Math.round((pj.beat || 0.05) * 100)
        + ' yenen en iyi model; yenen yoksa eğri ve fark değişmezse. Modeller: ' + Object.entries(pj.models || {}).map(([k, v]) => k + ' ' + v).join(' · ') },
      'Öngörülen (' + hzText + '): ', h('b', null, models.join(' · '))));
  }

  /** The main table: every fixed coupon bond, bill and zero coupon bond of the desk's list - Piyasa, Eğri, Fiyat with its
   * label, Fark; under each, closed, its details (the trading list's bonds: the row of the fair, the projection, the quote,
   * the levels and the market as before, unchanged). */
  drawTable(d) {
    const t = h('table', { class: 'plain kf kf-main-table', id: 'kf-table' });
    const g = (text, span, tip) => h('th', { class: 'kf-g kf-sep', colspan: String(span), title: tip || null }, text);
    t.appendChild(h('tr', { class: 'kf-main-groups' }, g('Kâğıt', 4), g('Piyasa', 3, 'Bugünkü piyasa fiyatı: iki taraflı kotanın ortası ya da bugünkü son '
        + 'işlem (trading listesi: DİBS RV; diğerleri: Tüm Kâğıtlar) - getirisi ve temiz fiyatı'),
      g('Eğri', 2, 'Vade kovasının tabanı (adil getirinin ağırlıkları): 1 yıla kadar %75 OIS sıfır faizi + %25 Nelson-Siegel, 1–5 yıl Nelson-Siegel, '
        + '5 yıl üstü %75 Nelson-Siegel + %25 OIS. Nelson-Siegel fiyatı olan kâğıtlara şimdi uydurulur, kâğıdın kendi nakit akışlarında (uydurmadaki '
        + 'kâğıt için kendisi dışarıda bırakılarak)'),
      g('Fiyat', 3, 'Cevap: piyasa fiyatı varsa o; yoksa eğri + kâğıdın son kapanıştaki eğriye farkı (son fark); geçmişi yoksa eğri + aynı vade '
        + 'kovasında bugün piyasa fiyatlı akranlarının eğriye farklarının medyanı (akran farkı; bono / kuponsuz bir arada, sabit kuponlu ayrı); '
        + 'akranı da yoksa eğri'), g('Fark', 1), g('', 1)));
    const heads = [['', ''], ['Kâğıt', 'l'], ['ISIN', 'l'], ['Vade', ''], ['Getiri %', 'kf-sep'], ['Temiz', ''], ['Kaynak', 'l'],
      ['Getiri %', 'kf-sep'], ['Temiz', ''], ['Getiri %', 'kf-sep'], ['Temiz', ''], ['Nereden', 'l'], ['bp', 'kf-sep'], ['Kart', '']];
    t.appendChild(h('tr', { class: 'kf-main-heads' }, ...heads.map(([x, c]) => h('th', { class: c || null }, x))));
    const rows = d.curve_rows || [];
    const old = {};
    for (const r of d.rows || []) old[r.isin] = r;
    for (const k of d.kinds || []) {
      const mine = rows.filter((r) => r.kind === k.kind);
      if (!mine.length) continue;
      t.appendChild(h('tr', { class: 'kf-kind' }, h('td', { class: 'l', colspan: String(MAIN_COLS) }, k.title + ' · ' + mine.length)));
      for (const r of mine) this.drawMain(t, r, old[r.isin], d);
    }
    if (!rows.length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: String(MAIN_COLS) }, d.why || 'Masanın listesinde fiyatlanacak kâğıt yok')));
    const others = (d.others || []).map((x) => x.text + ' ' + x.n).join(' · ');
    const c = d.counts || {};
    const foot = h('div', { class: 'muted kf-others', id: 'kf-others' },
      'Fiyat: piyasa ' + (c.market || 0) + ' · eğri + son fark ' + (c.spread || 0) + ' · eğri + akran farkı ' + (c.peer || 0) + ' · eğri ' + (c.curve || 0) + ' kâğıt'
      + (others ? ' · Eğriyle fiyatlanmaz (' + (d.others_why || '') + '): ' + others + ' - Tüm Kâğıtlar\'da' : ''));
    clear(this.table.body).append(t, foot);
  }

  drawMain(t, r, oldRow, d) {
    const tr = h('tr', { class: 'kf-main' + (r.price ? '' : ' kf-off') });
    tr.dataset.isin = r.isin;
    const isOpen = this.open.has(r.isin);
    const toggle = h('td', { class: 'act kf-toggle', title: 'Ayrıntılar: adil, kota, iyi seviyeler, σ, öngörülen, OIS / FX swap\'a göre' }, isOpen ? '▾' : '▸');
    const m = r.market, cv = r.curve, p = r.price;
    const mTip = m ? m.source + ': temiz ' + px(m.clean) + ' → getiri ' + yld(m.yield) + ' (bileşik), ' + yld(m.simple) + ' (basit) · valör ' + day(r.value_date)
      : 'Bugün piyasa fiyatı yok (iki taraflı kota da bugünkü işlem de yok)';
    const cTip = cv ? 'Eğri (' + cv.base + (cv.base !== 'eğri' ? ': Nelson-Siegel ' + yld(cv.ns) + (isNum(cv.ois) ? ', OIS ' + yld(cv.ois) : '') : '') + '): '
      + cv.fit + ' · getiri ' + yld(cv.yield) + ' (bileşik), ' + yld(cv.simple) + ' (basit) · temiz ' + px(cv.clean)
      + ' (valör ' + day(r.value_date) + ')' : (r.curve_why || 'eğri yok');
    const pTip = p ? (p.how || '') : (r.why || 'fiyatı yok');
    tr.append(toggle, cell(r.label || r.isin, { cls: 'l b', tip: r.name || r.isin }), cell(r.isin, { cls: 'l kf-isin' }), cell(day(r.maturity)),
      cell(m ? yld(m.yield) : '—', { cls: 'kf-mkt-y kf-sep' + (m ? '' : ' soft'), tip: mTip }), cell(m ? px(m.clean) : '—', { cls: 'kf-mkt-p' + (m ? '' : ' soft'), tip: mTip }),
      cell(m ? m.source : '—', { cls: 'l kf-mkt-src' + (m ? '' : ' soft') }),
      cell(cv ? yld(cv.yield) : '—', { cls: 'kf-crv-y kf-sep' + (cv ? '' : ' soft'), tip: cTip }), cell(cv ? px(cv.clean) : '—', { cls: 'kf-crv-p' + (cv ? '' : ' soft'), tip: cTip }),
      cell(p ? yld(p.yield) : '—', { cls: 'b kf-px-y kf-sep', tip: pTip }), cell(p ? px(p.clean) : '—', { cls: 'b kf-px-p', tip: pTip }),
      cell(p ? p.label : (r.why || 'fiyatı yok'), { cls: 'l kf-px-label kf-lab-' + (p ? p.kind : 'none'), tip: pTip }),
      cell(isNum(r.diff) ? bp(r.diff) : '', { cls: 'kf-diff kf-sep', tip: 'Piyasa − eğri (bp, bileşik getiri)' }),
      cell('kart', { cls: 'act cardlink', tip: 'Kâğıt kartı: ' + r.isin }));
    t.appendChild(tr);
    const det = h('tr', { class: 'kf-detail' + (isOpen ? '' : ' kf-closed') });
    det.dataset.isin = r.isin;
    const td = h('td', { class: 'l kf-detail-cell', colspan: String(MAIN_COLS) });
    // (the details scroll inside their own box: an open one does not stretch the main table's columns)
    td.appendChild(oldRow ? h('div', { class: 'kf-detail-wrap' }, this.oldTable(oldRow, d)) : h('p', { class: 'muted kf-detail-none' }, 'Ayrıntı yok: adil, kota, iyi seviyeler ve öngörülen '
      + 'yalnız trading listesindeki kâğıtlar için (Tüm Kâğıtlar\'da ☆ ile eklenir).' + (p ? ' Fiyat: ' + (p.how || '') : '')));
    det.appendChild(td);
    t.appendChild(det);
    toggle.addEventListener('click', () => {
      const now = !this.open.has(r.isin);
      if (now) this.open.add(r.isin); else this.open.delete(r.isin);
      toggle.textContent = now ? '▾' : '▸';
      det.classList.toggle('kf-closed', !now);
    });
  }

  /** A bond's details: the row the page showed before the main table (the fair, Öngörülen, OIS'e / FX swap'a göre, the
   * quote, the levels, the market, the context) and how it was priced - the same cells, the same numbers. */
  oldTable(r, d) {
    const t = h('table', { class: 'plain kf kf-old' });
    const g = (text, span, tip, id) => h('th', { class: 'kf-g kf-sep', colspan: String(span), title: tip || null, id: id || null }, text);
    const pj = d.projection || {};
    const hzText = ((pj.horizons || []).find((x) => x.h === this.hz) || {}).text || '';
    t.appendChild(h('tr', { class: 'kf-groups' }, g('Kâğıt', 4), g('Adil getiri', 3, 'Tabanlar + son kapanıştaki fark, vadeye göre ağırlıklı'),
      g('Öngörülen · ' + hzText, 6, 'Bir süre sonra (seçilen ufukta) ulaşması beklenen getiri ve fiyat: kovanın ve ufkun modeli masanın geçmişinde '
        + 'örnek dışı seçildi (' + (pj.source || '') + '); "değişmez"i en az %' + Math.round((pj.beat || 0.05) * 100) + ' yenen yoksa eğri ve fark '
        + 'değişmezse. Fiyat ufkun valöründe temiz; Δ şimdiki getiriden (bp); K/Z 1 mn nominal alışın bu değişimden (taşıma / fonlama hariç). '
        + 'Üzerine gelince model, hesap ve geri test.'),
      g("OIS'e göre", 2, "DİBS Trading'in \"OIS'e göre\" sütunları: kâğıdın ASW'si DİBS RV'nin OIS ASW eğrisinde (a + b·t + c·t²) dursaydı getirisi ve "
        + 'valördeki temiz fiyatı (rvfair)'),
      g("FX swap'a göre", 2, "DİBS Trading'in \"FX swap'a göre\" sütunları: kâğıdın ASW FX'i DİBS ASW'nin FX swap ima eğrisindeki ASW eğrisinde "
        + 'dursaydı getirisi ve valördeki temiz fiyatı (rvfair)'),
      g('Kotan', 3, 'Adil ± genişliğin yarısı (bileşik getiri)'), g('İyi seviyeler', 4, 'Al: adil + 2σ ya da üstü · Sat: adil − 2σ ya da altı'),
      g('Piyasa şimdi', 3, 'Adilden σ cinsinden; AL: offer adil + 2σ ya da üstünde, SAT: bid adil − 2σ ya da altında'), g('Bağlam', 1)));
    const heads = [['Kâğıt', 'l'], ['', ''], ['Vade', ''], ['Kalan', ''], ['Bileşik %', 'kf-sep'], ['Basit %', ''], ['Temiz', ''],
      ['Bileşik %', 'kf-sep'], ['Basit %', ''], ['Temiz', ''], ['Δ bp', ''], ['K/Z 1 mn', ''], ['Model', ''],
      ['Adil getiri %', 'kf-sep'], ['Adil fiyat', ''], ['Adil getiri %', 'kf-sep'], ['Adil fiyat', ''],
      ['Bid %', 'kf-sep'], ['Ask %', ''], ['Bid / ask temiz', ''], ['Al ≥ %', 'kf-sep'], ['Sat ≤ %', ''], ['σ bp', ''], ['Geri test', ''],
      ['Ekran', 'kf-sep'], ['Broker bid / offer', ''], ['BBG bid / ask', ''], ['Fark · medyan', 'kf-sep']];
    t.appendChild(h('tr', { class: 'kf-heads' }, ...heads.map(([x, c]) => h('th', { class: c || null }, x))));
    this.drawRow(t, r, d.rules);
    return t;
  }

  drawRow(t, r, rules) {
    const tr = h('tr', { class: 'kf-row' + (r.priced ? '' : ' kf-off') });
    tr.dataset.isin = r.isin;
    tr.append(cell(r.label || r.isin, { cls: 'l b', tip: r.isin }), cell('▸', { cls: 'act cardlink', tip: 'Kâğıt kartı: ' + r.isin }),
      cell(day(r.maturity)), cell(isNum(r.years) ? num(r.years, 2, false) : '', { tip: r.bucket_text ? 'Kova ' + r.bucket_text : '' }));
    // "OIS'e göre" / "FX swap'a göre": DİBS Trading's two cells of each curve (the same values; soft outside the bonds fitted)
    const aswCells = () => ASW.flatMap(([key, name]) => {
      const a = (r.asw || {})[key];
      if (!a || a.why || !isNum(a.yield)) {
        const tip = a ? aswTip(a, name) : name + ': yok';
        return [cell('–', { cls: 'soft kf-sep kf-' + key + '-y', tip }), cell('–', { cls: 'soft kf-' + key + '-p', tip })];
      }
      const tip = aswTip(a, name);
      return [cell(yld(a.yield), { cls: 'kf-sep kf-' + key + '-y' + (a.soft ? ' soft' : ''), tip }),
        cell(px(a.price), { cls: 'kf-' + key + '-p' + (a.soft ? ' soft' : ''), tip })];
    });
    if (!r.priced) {
      tr.append(cell(r.why || '', { cls: 'l muted kf-why kf-sep', span: WHY_SPAN }), ...aswCells(), cell('', { span: REST_SPAN }));
      t.appendChild(tr);
      return;
    }
    const f = r.fair, q = r.quote, lv = r.levels, s = r.sigma || {};
    const mk = r.market || [];
    const side = (src) => {
      const ms = mk.filter((m) => m.src === src);
      if (!ms.length) return cell('–', { cls: 'soft kf-mkt', tip: src === 'broker' ? 'Broker Chat tahtasında taze bid / offer yok' : 'Canlı Bloomberg bid / ask yok' });
      const td = h('td', { class: 'kf-mkt' });
      ms.forEach((m, i) => {
        if (i) td.appendChild(document.createTextNode(' / '));
        td.appendChild(h('span', { title: marketTip(m), class: m.signal ? 'kf-sig ' + (m.signal === 'AL' ? 'pos' : 'neg') : null },
          quoteText(m) + (m.signal ? ' ' + m.signal : '')));
      });
      return td;
    };
    const ctx = r.context || {};
    // Öngörülen at the horizon chosen
    const e = projAt(r, this.hz);
    const p = r.proj || {};
    let projCells;
    if (e && isNum(e.yield)) {
      const tip = projTip(e, p);
      const tone = (v) => (isNum(v) && Math.round(v) !== 0 ? (v > 0 ? ' pos' : ' neg') : '');
      projCells = [cell(yld(e.yield), { cls: 'kf-proj kf-sep', tip }),
        cell(yld(e.simple), { cls: 'kf-proj-simple', tip: 'BIST basit getiri (ufkun valöründe, ' + day(e.value_date) + ')' }),
        cell(px(e.clean), { cls: 'kf-proj-price', tip: 'Öngörülen getirinin ufkun valöründeki (' + day(e.value_date) + ') temiz fiyatı' }),
        cell(bp(e.bp), { cls: 'kf-proj-bp' + tone(-e.bp), tip: (p.from === 'ekran' ? 'Ekran getirisinden' : 'Şimdiki getiriden (komşu eğri + son kapanış farkı)')
          + ' öngörülene, bileşik getiri bp' }),
        cell(tl(e.pnl), { cls: 'kf-proj-pnl' + tone(e.pnl), tip: '1 mn nominal alışın öngörülen getiri değişiminden K/Z\'si (TL): ufkun valöründe iki getirinin '
          + 'temiz fiyat farkı × 10.000; taşıma ve fonlama dahil değil' }),
        cell(modelShort(e), { cls: 'kf-proj-model' + (e.beat && !e.why ? '' : ' soft'), tip })];
    } else {
      projCells = [cell('–', { cls: 'soft kf-proj kf-sep', tip: (e && e.why) || p.why || 'Öngörülen yok', span: 6 })];
    }
    tr.append(cell(yld(f.yield), { cls: 'b kf-fair kf-sep', tip: r.line }), cell(yld(f.simple), { tip: 'BIST basit getiri' }),
      cell(px(f.clean), { cls: 'kf-price', tip: 'Valör ' + day(r.value_date) + ' (DİBS RV)' }),
      ...projCells, ...aswCells(),
      cell(yld(q.bid.yield), { cls: 'kf-bid kf-sep', tip: 'Adil + ' + num(q.width / 2, 1, false) + ' bp · temiz ' + px(q.bid.clean) }),
      cell(yld(q.ask.yield), { cls: 'kf-ask', tip: 'Adil − ' + num(q.width / 2, 1, false) + ' bp · temiz ' + px(q.ask.clean) }),
      cell(px(q.bid.clean) + ' / ' + px(q.ask.clean), { cls: 'kf-quote-px', tip: 'Genişlik ' + num(q.width, 1, false) + ' bp (' + (r.bucket_text || '') + ')' }),
      cell(yld(lv.buy.yield), { cls: 'kf-buy buy kf-sep', tip: 'Getiri bunun üstündeyse ucuz - al · temiz ' + px(lv.buy.clean) + ' ya da altı' }),
      cell(yld(lv.sell.yield), { cls: 'kf-sell sell', tip: 'Getiri bunun altındaysa pahalı - sat · temiz ' + px(lv.sell.clean) + ' ya da üstü' }),
      cell(num(s.sigma, 0) + (s.short ? '*' : ''), { cls: 'kf-sigma', tip: sigmaTip(s, r) + '\nGürültü bandı ±1σ: ' + yld(lv.noise[0].yield) + ' – ' + yld(lv.noise[1].yield) }),
      cell(hitText(r.backtest), { cls: 'kf-hit', tip: hitTip(r.backtest, rules) }),
      cell(isNum(r.z) ? yld(r.yield) + ' · ' + sig(r.z) : '–', { cls: 'kf-now kf-sep', tip: 'DİBS RV\'nin şimdiki bileşik getirisi (kullanılan fiyattan) ve adilden uzaklığı' }),
      side('broker'), side('bbg'),
      cell(isNum(ctx.now) ? bp(ctx.now) + ' · ' + bp(ctx.median) : '–', { cls: 'kf-ctx kf-sep', tip: 'Komşu eğriye fark şimdi (bp) · son ' + (ctx.n || 0) + ' kapanıştaki medyanı' }));
    t.appendChild(tr);
    const how = h('tr', { class: 'kf-how' });
    how.dataset.isin = r.isin;
    const td = h('td', { class: 'l', colspan: String(COLS) }, h('span', { class: 'muted' }, 'Nasıl fiyatlandı: '), r.line || '',
      r.note ? h('span', { class: 'muted kf-note' }, ' (' + r.note + ')') : '');
    if (e) {
      td.appendChild(h('span', { class: 'kf-proj-how' }, h('span', { class: 'muted' }, 'Öngörülen: '), e.line || e.why || '',
        h('span', { class: 'muted' }, ' · ' + e.record + (e.why && e.line ? ' · ' + e.why : ''))));
    }
    how.appendChild(td);
    t.appendChild(how);
  }

  drawWidths(d) {
    const w = d.widths || {};
    const buckets = (d.rules || {}).buckets || [];
    // (drawn again only when something in it changed - not under an administrator typing a width)
    const key = JSON.stringify([w, d.admin, d.log || []]);
    const typing = document.activeElement && document.activeElement.tagName === 'INPUT' && this.widths.body.contains(document.activeElement);
    if (key === this.widthsKey || typing) return;
    this.widthsKey = key;
    const body = clear(this.widths.body);
    const t = h('table', { class: 'plain kf-widths-table' });
    t.appendChild(h('tr', null, ...buckets.map((b) => h('th', null, b.text))));
    const inputs = {};
    t.appendChild(h('tr', null, ...buckets.map((b) => {
      if (!d.admin) return h('td', { id: 'kf-width-' + b.key }, num(w[b.key], 1, false) + ' bp');
      const inp = h('input', { class: 'inp', id: 'kf-width-' + b.key, value: num(w[b.key], 1, false), size: '5', inputmode: 'decimal' });
      inputs[b.key] = inp;
      return h('td', null, inp);
    })));
    body.appendChild(t);
    const said = (w.by ? 'Son değişiklik: ' + w.by + ' · ' + (w.at || '') : 'Varsayılan: her kovada 10 bp');
    if (d.admin) {
      const save = h('button', { class: 'btn', type: 'button', id: 'kf-widths-save' }, 'Kaydet');
      save.addEventListener('click', async () => {
        const widths = {};
        for (const [k, inp] of Object.entries(inputs)) widths[k] = inp.value.trim().replace(',', '.');
        try {
          await api.post('/api/kagit-fiyat/genislik', { widths });
          toast('Kotasyon genişliği kaydedildi', 'ok');
          this.ctx.refreshNow();
        } catch (err) { errorToast(err); }
      });
      body.appendChild(h('div', { class: 'kf-widths-foot' }, save, h('span', { class: 'muted' }, ' ' + said)));
      if ((d.log || []).length) {
        body.appendChild(h('ul', { class: 'muted kf-log', id: 'kf-log' }, ...d.log.map((x) => h('li', null, x.at + ' · ' + x.by + ' · ' + x.text))));
      }
    } else {
      body.appendChild(h('p', { class: 'muted' }, 'Genişliği yöneticiler değiştirir. ' + said));
    }
  }

  destroy() {}
}
