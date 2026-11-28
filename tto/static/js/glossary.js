// The curves' names, said once (the desk, 28.11.2026, B4: "Bir büyüklük: tek ad, tek sayı" - the offshore TRY curve had four
// names on the pages: ICAP, Offshore, FX swap ima, XCCY).  A short glossary for a page's "?" chip, under the cell colours'
// legend (pages/view.js): the one name the pages use for each curve, its parts, and the rules a figure is read by.
import { h } from './ui.js';

/** [term, what it means] - Turkish, as the pages. */
export const GLOSSARY = [
  ['Offshore', 'Offshore TRY eğrisi: 9A\'ya kadar FX swap ima faizleri, 1Y\'den XCCY. 18A hesaplanır, kota değildir. '
    + 'OIS\'ten ayrı bir eğridir: biri ötekinin yerine kullanılmaz.'],
  ['FX swap ima', 'Offshore eğrisinin 1H–9A kısmı: USDTRY swap puanlarının ima ettiği TRY faizi (TRYI…, basit ACT/360).'],
  ['XCCY', 'Offshore eğrisinin 1Y–10Y kısmı: çapraz kur swap kotaları (TRYSAQ1…10, yıllık ACT/360 par; 1Y = TRYSAQ1), '
    + 'zero\'ları bootstrap ile.'],
  ['ICAP', 'Fiyat kaynağı (Bloomberg ICPL): offshore kotalarının geldiği yer - bir eğrinin adı değil.'],
  ['OIS', 'TRY OIS: TLREF OIS kotaları (TYSO…), ACT/365; 3A\'ya kadar tek ödeme, sonra çeyreklik. Bootstrap = Murex\'in eğrisi '
    + '(MTM), PPK basamak kişisel ikinci görünüm.'],
  ['Spot', 'USDTRY spotu her sayfada üst şeridinki: Spot kaynağı BBG (USDTRY bid / ask ortası) ya da manuel spot.'],
  ['X − OIS (bp)', 'Spread kuralı: bir faizin aynı vadenin OIS faizinden farkı, bp, tam sayı; taraf başlıkta (bid / ask / mid / '
    + 'son). Offshore\'a göre olanlar "X − Offshore".'],
];

/** The glossary as a node for a menu (``{ node }`` item of ui.js menu). */
export function glossaryNode() {
  const dl = h('dl', { class: 'glossary', id: 'curve-glossary' });
  for (const [term, text] of GLOSSARY) {
    dl.appendChild(h('dt', null, term));
    dl.appendChild(h('dd', null, text));
  }
  return dl;
}
