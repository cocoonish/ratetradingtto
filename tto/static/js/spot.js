// Manual USDTRY spot: the two "Manuel SP" cells of the VİOP sheet, reachable from the header strip of every page.
// They are a shared input: what is typed here replaces the Bloomberg spot for everyone until it is cleared.
import { api } from './api.js';
import { h, modal, toast, errorToast } from './ui.js';
import { raw, parseNumber } from './format.js';

export async function openSpotEditor(ctx) {
  let data;
  try { data = await api.get('/api/spot'); } catch (err) { errorToast(err); return; }
  if (!data.available) { toast('Bu çalışma kitabında manuel spot hücreleri yok', 'err'); return; }
  const m = modal({ title: 'Manuel spot  ·  USDTRY', width: 440 });
  const bid = h('input', { type: 'text', class: 'inp num', autocomplete: 'off', id: 'spot-bid', value: raw(data.bid) });
  const ask = h('input', { type: 'text', class: 'inp num', autocomplete: 'off', id: 'spot-ask', value: raw(data.ask) });
  const state = h('b', { id: 'spot-source' }, data.source || '—');
  m.body.appendChild(h('p', { class: 'muted', style: { margin: '0 0 12px' } },
    'Girilen bid / ask herkes için geçerlidir ve tüm sayfalardaki USDTRY spotunun yerine geçer. ',
    'Boş bırakılırsa Bloomberg spotu (USDTRY Curncy) kullanılır.'));
  m.body.appendChild(h('div', { class: 'spot-form' },
    h('label', { for: 'spot-bid' }, 'Bid'), bid, h('label', { for: 'spot-ask' }, 'Ask'), ask,
    h('span', { class: 'muted' }, 'Şu an'), state));

  const apply = async (b, a, done) => {
    try {
      const res = await ctx.setInputs(data.book, [{ ref: data.refs.bid, value: b }, { ref: data.refs.ask, value: a }]);
      if (res.errors && res.errors.length) { toast(res.errors.join('; '), 'err', 7000); return; }
      toast(done, 'ok');
      ctx.refreshNow();
      m.close();
    } catch (err) { errorToast(err); }
  };
  const save = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
  save.addEventListener('click', () => {
    const b = bid.value.trim(), a = ask.value.trim();
    if (!b && !a) { apply('', '', 'Manuel spot kaldırıldı – Bloomberg spotu kullanılıyor'); return; }
    const x = parseNumber(b, true), y = parseNumber(a, true);
    if (x === null || y === null || x <= 0 || y <= 0) { toast('Bid ve ask birlikte, sayı olarak girilmeli (ya da ikisi de boş bırakılmalı)', 'err', 5000); return; }
    if (x > y) { toast('Bid, ask\'tan büyük olamaz', 'err', 4000); return; }
    apply(b, a, 'Manuel spot kaydedildi');
  });
  const clearBtn = h('button', { class: 'btn', type: 'button', title: 'İki hücreyi de boşalt: Bloomberg spotu kullanılır' }, 'Bloomberg\'e dön');
  clearBtn.addEventListener('click', () => apply('', '', 'Manuel spot kaldırıldı – Bloomberg spotu kullanılıyor'));
  m.box.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } });
  m.foot.appendChild(clearBtn);
  m.foot.appendChild(h('span', { class: 'grow' }));
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  m.foot.appendChild(save);
  bid.focus();
  bid.select();
}
