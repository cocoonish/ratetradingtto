// Trend (tto/quanttrend.py), a tab of Sinyaller: the family's every line on one table - its group, the score and the
// three horizons' contributions, the direction ("YENİ" when it turned since the previous close), the size in the desk's
// unit, the days in the direction, the walk-forward's hit rate and Sharpe; a click draws the line's series and its card.
// Below it the strength buckets the targets and holdings come from, and each group's record.
import { h, clear } from '../ui.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, groupText, T, N, pref, keep, pct, isNum, money, sideClass } from './quantbase.js';

const GROUP_PREF = 'tto.quant.trend.group';

/** A contribution's colour: red up, blue down, deeper as it nears ±1 (the score's scale). */
function tone(v) {
  if (!isNum(v) || Math.abs(v) < 0.02) return null;
  const a = Math.min(1, Math.abs(v));
  const base = v > 0 ? [230, 103, 103] : [57, 135, 229];
  return base.map((c) => Math.round(128 + (c - 128) * a).toString(16).padStart(2, '0')).join('').toUpperCase();
}

class TrendPage extends QuantPage {
  constructor(host, ctx) {
    super(host, ctx, 'trend');
    this.group = pref(GROUP_PREF, '');
  }

  build() {
    this.groupBar = h('div', { class: 'seg', id: 'quant-trend-group' });
    this.tools([h('span', { class: 'muted' }, 'Grup'), this.groupBar]);
    const page = this.pageEl();
    this.table = panel('quant-trend-table', 'Trend · her enstrüman bir satır');
    this.table.note.textContent = 'Skor: 1A, 3A ve 1Y getirisinin (enstrümanın kendi K/Z biriminde: FX\'te carry dahil, faiz, fly ve spread\'de bp, vol\'de '
      + 'vol puanı) günlük σ (son 60 hareket) × √gün\'e bölümünün ortalaması, ±2 ile sınırlı; 1A / 3A / 1Y sütunları her ufkun skora katkısı '
      + '(toplamları sınırlanmadan önceki skor), bir yıldan kısa geçmişte uzun ufuk eldeki gün kadardır, 63 günden kısa geçmişte satır yoktur. '
      + 'Büyüklük: masa ayarındaki günlük risk ÷ bir birimin günlük σ\'sı (USD), iki anlamlı basamak, 0,1 – 10 birim. Gün: yönün son '
      + 'dönüşünden beri geçen kapanış. İsabet: yön dönüşünden bir sonraki dönüşe ya da stopa kadar tutulan işlemlerin kârla kapananları '
      + '(enstrümanda 10 işlem yoksa grubunki); Sharpe: aynı riskle tutulan pozisyonun günlük K/Z\'sinden, yıllık.';
    this.boxes.table = new GridBox(this.table, 'quant/trend/table', (sid, click) => this.pick(sid, click), { freeze: 1 });
    const cp = panel('quant-trend-chart', 'Seçili satır', { wide: true, cls: 'qcardp' });
    this.chart = new SignalChart(cp.body);
    this.buckets = panel('quant-trend-buckets', 'Güç dilimleri · hedef ve tutma buradan');
    this.buckets.note.textContent = 'Her geçmiş günün satırı o gün çizildiği gibi (yalnızca o güne kadarki kapanışlarla, stop\'u o güne kadarki '
      + 'tutmalardan) yön dönene ya da stopa kadar izlenir; hâlâ açık olanlar son kapanıştaki kârlarıyla sayılır. Ort. kazanç: satırın gününün '
      + 'σ\'sı cinsinden; bir satırın hedefi o güçteki kendi satırlarının (40\'tan azsa grubunun, o da azsa ailenin) ortalaması × bugünkü σ.';
    this.boxes.buckets = new GridBox(this.buckets, 'quant/trend/buckets');
    this.groups = panel('quant-trend-groups', 'Grupların geri testi', { cls: 'aux' });
    this.groups.note.textContent = 'Yürüyen pencere: her gün yalnızca o güne kadarki kapanışlar. İşlem: ilk günün ya da her yön dönüşünün satırı, '
      + 'bir sonraki dönüşe ya da stopa kadar (stoptan sonra yeni dönüşe kadar pozisyon yok). Sharpe: grubun satırları aynı riskle tutulsaydı '
      + 'günlük K/Z toplamının ortalaması ÷ σ × √252.';
    this.boxes.groups = new GridBox(this.groups, 'quant/trend/groups');
    page.append(this.table.el, cp.el, this.buckets.el, this.groups.el);
    this.host.appendChild(page);
  }

  /** The group buttons: "Tümü" and every group that has a row, the chosen one lit (a filter of the table here). */
  fillGroups(rows) {
    const groups = [...new Set(rows.map((r) => r.group))];
    if (this.group && !groups.includes(this.group)) this.group = '';
    const items = [['', 'Tümü']].concat(groups.map((g) => [g, g]));
    if (this.groupBar.dataset.items !== JSON.stringify(items)) {
      clear(this.groupBar);
      for (const [g, label] of items) {
        const b = h('button', { type: 'button' }, label);
        b.dataset.v = g;
        b.addEventListener('click', () => { this.group = g; keep(GROUP_PREF, g); this.fill(); });
        this.groupBar.appendChild(b);
      }
      this.groupBar.dataset.items = JSON.stringify(items);
    }
    for (const b of this.groupBar.children) b.classList.toggle('on', b.dataset.v === this.group);
  }

  fill() {
    this.fillStatus();
    const d = this.data || {};
    if (!d.ready) {
      this.boxes.table.set([], [], null, 'İlk hesap yapılıyor…');
      return;
    }
    const tr = d.trend || {};
    if (tr.ok === false) {
      this.boxes.table.set([], [], null, tr.why || 'Trend hesaplanamadı');
      return;
    }
    const all = tr.rows || [];
    this.fillGroups(all);
    const rows = all.filter((r) => !this.group || r.group === this.group);
    this.table.setTitle('Trend · her enstrüman bir satır · ' + (tr.lines || 0) + ' satır, ' + (tr.instruments || 0) + ' enstrüman · hedef günlük risk '
      + money(tr.risk_usd, 'USD', false));
    this.boxes.table.set(['İşlem', 'Giriş', 'Hedef', 'Stop', 'Beklenen', 'Ödül / risk', 'İsabet', 'Büyüklük', 'Skor', '1A', '3A', '1Y', 'Gün', 'Tutma (g)',
      'Sharpe', 'Grup', 'Not'],
      rows.map((r) => {
        const terms = r.terms || [];
        const labels = r.labels || ['1A', '3A', '1Y'];
        const hit = isNum(r.hit) ? pct(r.hit) + ' (' + r.trades + (r.scope === 'grup' ? ', grup' : '') + ')' : (r.trades ? '' : '— (0)');
        const note = r.why || (r.stopped ? 'stop oldu' + (r.stopped_at ? ' (' + isoToTr(r.stopped_at) + ')' : '') + ': yeni dönüşe kadar pozisyon yok' : '');
        // (the line's levels in the instrument's own price - an FX forward's -, as its line in the Sinyaller list; a trailing stop has no target)
        const px = r.px || null;
        const lv = (k) => (px ? N(px[k], px.digits, k === 'target' ? { empty: 'iz süren stop' } : {})
          : N(r[k], isNum(r.digits) ? r.digits : 2, k === 'target' && r.sid && isNum(r.entry) ? { empty: 'iz süren stop' } : {}));
        const side = sideClass(r.verb);
        return [T((r.verb ? r.verb + ' ' : '') + r.label + (r.new ? ' · YENİ' : ''), Object.assign({ b: 1, tip: r.line || '' }, side ? { cls: side } : {})),
          lv('entry'), lv('target'), lv('stop'),
          T(isNum(r.exp) ? money(r.exp, r.ccy) : '', { tip: r.levels || (r.bucket ? '|skor| ' + r.bucket + ' diliminin ortalaması' : '') }),
          N(r.rr, 2),
          // (the record of the instrument's own positions; the list's line says its group's trailing stop's - the tooltip)
          T(hit, { tip: r.levels ? 'İz süren stop (grubun): ' + r.levels : '' }),
          T(r.size || ''),
          N(r.score, 2, { sign: true, b: isNum(r.score) && Math.abs(r.score) >= 1 ? 1 : 0, tip: r.strength || '' }),
          ...[0, 1, 2].map((i) => N(terms[i], 2, { sign: true, heat: tone(terms[i]), tip: labels[i] + ' ufkunun skora katkısı' })),
          N(r.days_in, 0), N(r.hold, 0), N(r.sharpe, 2, { sign: true }),
          T(groupText(r), r.tag ? { cls: 'qtag', tip: r.tag + ': masanın offshore işlem limiti dar' } : {}), T(note, { cls: r.why ? 'soft' : '' })];
      }), rows.map((r) => r.sid || null), this.group ? this.group + ' grubunda satır yok' : 'Evrende enstrüman yok', this.picked);
    const bk = tr.buckets || [];
    this.boxes.buckets.set(['Grup', '|Skor|', 'Satır', 'Ort. kazanç (σ)', 'Ort. tutma (g)', 'İsabet'], bk.filter((r) => r.n).map((r) => [
      T(r.group, { b: r.group === 'Tümü' ? 1 : 0 }), T(r.bucket), N(r.n, 0), N(r.gain, 2, { sign: true, cls: isNum(r.gain) && r.gain <= 0 ? 'soft' : '' }),
      N(r.hold, 0), T(pct(r.hit))]), null, 'Geri testte satır yok (63 günden uzun geçmiş gerekir)');
    this.boxes.groups.set(['Grup', 'Satır', 'İşlem', 'İsabet', 'Sharpe'], (tr.groups || []).map((g) => [T(g.group, { b: g.group === 'Tümü' ? 1 : 0 }),
      N(g.lines, 0), N(g.trades, 0), T(pct(g.hit)), N(g.sharpe, 2, { sign: true })]), null, 'Geri testte işlem yok');
    if (!this.picked) {
      const first = rows.find((r) => r.sid && r.new) || rows.find((r) => r.sid);
      this.firstPick(first ? [first] : [], 'Şu an trend satırı yok (geçmiş kısa satırların nedeni tabloda): bir satır olunca serisi burada çizilir.');
    }
  }

  afterPick() {
    this.fill();
  }
}

export const TREND_PAGES = { 'quant-trend': TrendPage };
