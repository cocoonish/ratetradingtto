// Kâğıt Fiyatlama (tto/kagitfiyat.py): every fixed coupon bond and bill of the trading list with one fair level - the
// neighbours' curve (Nelson-Siegel of the other bonds) and OIS, each plus the bond's spread at the last close, weighted by
// maturity -, a quote around it, the good levels (fair ± 2σ) with their backtest, the market now against them and, under
// each bond, how the price was built.  The quote's width is the administrators' (typed here, logged).
import { api } from '../api.js';
import { h, clear, toast, errorToast } from '../ui.js';
import { num } from '../format.js';
import { bondCardLinks } from '../bonds.js';
import { isNum, yld, px, bp, sig, day, hitText, hitTip, sigmaTip, quoteText, marketTip } from '../kagitblock.js';

const COLS = 18;                                       // the table's columns (the how-line and a reason span them)

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
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools kf-tools', id: 'kf-tools' });
    this.info = h('span', { class: 'muted', id: 'kf-info' });
    tools.append(h('b', null, 'Kâğıt Fiyatlama'), this.info, h('span', { class: 'grow' }), h('span', { class: 'muted', id: 'kf-time' }));
    this.host.appendChild(tools);
    this.rules = h('div', { class: 'chips kf-rules', id: 'kf-rules' });
    this.host.appendChild(this.rules);
    const panels = h('div', { class: 'panels' });
    this.table = panel('kf-panel', 'Trading listesi · adil getiri, kotan, iyi seviyeler, piyasa',
      'Adil getiri: tabanlar (komşu eğri: trading listesinin diğer sabit kuponlularına uydurulan Nelson-Siegel eğrisi, kâğıt dışarıda; OIS: '
      + 'TRY OIS Bootstrap sıfır faizi vadede) + kâğıdın son kapanıştaki farkı, vadeye göre ağırlıklı. Getiriler BIST bileşik (basit yanında), fiyat '
      + 'DİBS RV valöründe temiz. Al: getiri adil + 2σ ya da üstünde (ucuz); Sat: adil − 2σ ya da altında (pahalı); ±1σ gürültü. σ kâğıdın son '
      + '60 kapanıştaki sonraki-gün hatası, kovanın tabanıyla. Piyasa: Broker Chat tahtasının en iyi taze bid / offer\'ı ve Bloomberg canlı bid / '
      + 'ask (DİBS RV), adilden σ cinsinden. Hücrelerin üzerine gelince hesabı; ▸ kâğıt kartı.');
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
    this.drawInfo(d);
    this.drawRules(d);
    this.drawTable(d);
    this.drawWidths(d);
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
  }

  drawTable(d) {
    const t = h('table', { class: 'plain kf', id: 'kf-table' });
    const g = (text, span, tip) => h('th', { class: 'kf-g', colspan: String(span), title: tip || null }, text);
    t.appendChild(h('tr', { class: 'kf-groups' }, g('Kâğıt', 4), g('Adil getiri', 3, 'Tabanlar + son kapanıştaki fark, vadeye göre ağırlıklı'),
      g('Kotan', 3, 'Adil ± genişliğin yarısı (bileşik getiri)'), g('İyi seviyeler', 4, 'Al: adil + 2σ ya da üstü · Sat: adil − 2σ ya da altı'),
      g('Piyasa şimdi', 3, 'Adilden σ cinsinden; AL: offer adil + 2σ ya da üstünde, SAT: bid adil − 2σ ya da altında'), g('Bağlam', 1)));
    const heads = [['Kâğıt', 'l'], ['', ''], ['Vade', ''], ['Kalan', ''], ['Bileşik %', ''], ['Basit %', ''], ['Temiz', ''],
      ['Bid %', ''], ['Ask %', ''], ['Bid / ask temiz', ''], ['Al ≥ %', ''], ['Sat ≤ %', ''], ['σ bp', ''], ['Geri test', ''],
      ['Ekran', ''], ['Broker bid / offer', ''], ['BBG bid / ask', ''], ['Fark · medyan', '']];
    t.appendChild(h('tr', { class: 'kf-heads' }, ...heads.map(([x, c]) => h('th', { class: c || null }, x))));
    const rows = d.rows || [];
    const kinds = d.kinds || [];
    for (const k of kinds) {
      const mine = rows.filter((r) => r.kind === k.kind);
      if (!mine.length) continue;
      t.appendChild(h('tr', { class: 'kf-kind' }, h('td', { class: 'l', colspan: String(COLS) }, k.title + ' · ' + mine.length)));
      for (const r of mine) this.drawRow(t, r, d.rules);
    }
    if (!rows.length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: String(COLS) }, 'Trading listesi boş: Tüm Kâğıtlar sayfasında ☆ ile ekleyin')));
    clear(this.table.body).appendChild(t);
  }

  drawRow(t, r, rules) {
    const tr = h('tr', { class: 'kf-row' + (r.priced ? '' : ' kf-off') });
    tr.dataset.isin = r.isin;
    tr.append(cell(r.label || r.isin, { cls: 'l b', tip: r.isin }), cell('▸', { cls: 'act cardlink', tip: 'Kâğıt kartı: ' + r.isin }),
      cell(day(r.maturity)), cell(isNum(r.years) ? num(r.years, 2, false) : '', { tip: r.bucket_text ? 'Kova ' + r.bucket_text : '' }));
    if (!r.priced) {
      tr.appendChild(cell(r.why || '', { cls: 'l muted kf-why', span: COLS - 4 }));
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
    tr.append(cell(yld(f.yield), { cls: 'b kf-fair', tip: r.line }), cell(yld(f.simple), { tip: 'BIST basit getiri' }),
      cell(px(f.clean), { cls: 'kf-price', tip: 'Valör ' + day(r.value_date) + ' (DİBS RV)' }),
      cell(yld(q.bid.yield), { cls: 'kf-bid', tip: 'Adil + ' + num(q.width / 2, 1, false) + ' bp · temiz ' + px(q.bid.clean) }),
      cell(yld(q.ask.yield), { cls: 'kf-ask', tip: 'Adil − ' + num(q.width / 2, 1, false) + ' bp · temiz ' + px(q.ask.clean) }),
      cell(px(q.bid.clean) + ' / ' + px(q.ask.clean), { tip: 'Genişlik ' + num(q.width, 1, false) + ' bp (' + (r.bucket_text || '') + ')' }),
      cell(yld(lv.buy.yield), { cls: 'kf-buy buy', tip: 'Getiri bunun üstündeyse ucuz - al · temiz ' + px(lv.buy.clean) + ' ya da altı' }),
      cell(yld(lv.sell.yield), { cls: 'kf-sell sell', tip: 'Getiri bunun altındaysa pahalı - sat · temiz ' + px(lv.sell.clean) + ' ya da üstü' }),
      cell(num(s.sigma, 0) + (s.short ? '*' : ''), { cls: 'kf-sigma', tip: sigmaTip(s, r) + '\nGürültü bandı ±1σ: ' + yld(lv.noise[0].yield) + ' – ' + yld(lv.noise[1].yield) }),
      cell(hitText(r.backtest), { cls: 'kf-hit', tip: hitTip(r.backtest, rules) }),
      cell(isNum(r.z) ? yld(r.yield) + ' · ' + sig(r.z) : '–', { cls: 'kf-now', tip: 'DİBS RV\'nin şimdiki bileşik getirisi (kullanılan fiyattan) ve adilden uzaklığı' }),
      side('broker'), side('bbg'),
      cell(isNum(ctx.now) ? bp(ctx.now) + ' · ' + bp(ctx.median) : '–', { cls: 'kf-ctx', tip: 'Komşu eğriye fark şimdi (bp) · son ' + (ctx.n || 0) + ' kapanıştaki medyanı' }));
    t.appendChild(tr);
    const how = h('tr', { class: 'kf-how' });
    how.dataset.isin = r.isin;
    how.appendChild(h('td', { class: 'l', colspan: String(COLS) }, h('span', { class: 'muted' }, 'Nasıl fiyatlandı: '), r.line || '',
      r.note ? h('span', { class: 'muted kf-note' }, ' (' + r.note + ')') : ''));
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
