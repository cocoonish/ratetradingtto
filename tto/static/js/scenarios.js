// Senaryolar: named snapshots of a user's personal inputs (both workbooks), stored under the user's name.
import { api, session } from './api.js';
import { h, clear, modal, toast, errorToast, confirmDialog } from './ui.js';
import { pendingWrites, trackWrite } from './grid.js';

/** Load a saved scenario after every input write still in flight (a cell just typed - its editor committed first -, a
 *  block pasted, a reset): the server applies the load after the writes it has (in their queue's order), and waiting
 *  for their answers makes sure it has them all - the scenario's values stand, never a value typed a moment before. */
export async function loadScenario(name) {
  await pendingWrites();
  return api.post('/api/scenarios/load', { name });
}

export async function openScenarios(ctx) {
  const m = modal({ title: 'Senaryolarım · ' + (session.display || ''), width: 720 });
  const list = h('div');
  const mine = h('div');
  const name = h('input', { class: 'inp', type: 'text', placeholder: 'Senaryo adı (örn. PPK -250bp)', maxlength: '60', style: { flex: '1' } });
  const save = h('button', { class: 'btn primary', type: 'button' }, 'Şu anki girdilerimi kaydet');
  let scenarios = [];

  const reload = async () => {
    const [sc, inp] = await Promise.all([api.get('/api/scenarios'), api.get('/api/my-inputs')]);
    scenarios = sc.scenarios;
    clear(list);
    if (!scenarios.length) {
      list.appendChild(h('div', { class: 'empty' }, 'Kayıtlı senaryonuz yok. Sayfalardaki sarı (kişisel) hücreleri değiştirip burada bir isimle kaydedin.'));
    } else {
      const table = h('table', { class: 'plain' });
      table.appendChild(h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Senaryo'), h('th', null, 'Hücre'), h('th', null, 'Güncelleme'), h('th', null, ''))));
      const body = h('tbody');
      for (const s of scenarios) {
        const load = h('button', { class: 'btn sm primary', type: 'button' }, 'Yükle');
        const del = h('button', { class: 'btn sm danger', type: 'button' }, 'Sil');
        load.addEventListener('click', async () => {
          try {
            const res = await loadScenario(s.name);
            toast('"' + s.name + '" yüklendi (' + res.cells + ' hücre)', 'ok');
            ctx.refreshNow();
            await reload();
          } catch (err) { errorToast(err); }
        });
        del.addEventListener('click', async () => {
          if (!(await confirmDialog('Senaryoyu sil', '"' + s.name + '" silinsin mi?', 'Sil', true))) return;
          try { await api.del('/api/scenarios', { name: s.name }); await reload(); } catch (err) { errorToast(err); }
        });
        body.appendChild(h('tr', null, h('td', { class: 'l' }, h('b', null, s.name)), h('td', null, String(s.cells)), h('td', null, s.updated_at),
          h('td', null, load, ' ', del)));
      }
      table.appendChild(body);
      list.appendChild(table);
    }
    clear(mine);
    const n = inp.inputs.length;
    const head = h('div', { class: 'field' }, h('label', null, 'Şu anki kişisel girdilerim (' + n + ' hücre)'));
    mine.appendChild(head);
    if (n) {
      const box = h('div', { class: 'mine-list' });
      const table = h('table', { class: 'plain' });
      const body = h('tbody');
      for (const x of inp.inputs.slice(0, 400)) {
        // (an input typed as a formula: the formula, then the value it gives now)
        const value = x.value === null ? '(boş)' : String(x.value);
        body.appendChild(h('tr', null, h('td', { class: 'l' }, x.ref),
          h('td', x.formula ? { title: 'Formül: ' + x.formula } : null, x.formula ? h('span', { class: 'mono' }, x.formula + '  →  ') : null, value),
          h('td', { class: 'l muted' }, x.label || '')));
      }
      table.appendChild(body);
      box.appendChild(table);
      mine.appendChild(box);
      const reset = h('button', { class: 'btn sm danger', type: 'button', style: { marginTop: '8px' } }, 'Tüm kişisel girdilerimi sıfırla');
      reset.addEventListener('click', async () => {
        if (!(await confirmDialog('Girdileri sıfırla', 'Tüm kişisel girdileriniz silinir ve dosyadaki değerlere dönülür. Kayıtlı senaryolar silinmez.', 'Sıfırla', true))) return;
        try {
          const books = [...new Set(inp.inputs.map((x) => x.book))];
          for (const b of books) await trackWrite(api.post('/api/reset', { book: b }));
          toast('Girdiler sıfırlandı', 'ok');
          ctx.refreshNow();
          await reload();
        } catch (err) { errorToast(err); }
      });
      mine.appendChild(reset);
    } else {
      mine.appendChild(h('div', { class: 'muted' }, 'Dosyadaki varsayılan değerlerle çalışıyorsunuz.'));
    }
  };

  const doSave = async () => {
    const nm = name.value.trim();
    if (!nm) { toast('Senaryoya bir isim verin', 'err'); name.focus(); return; }
    if (scenarios.some((s) => s.name.toLocaleLowerCase('tr') === nm.toLocaleLowerCase('tr'))) {
      if (!(await confirmDialog('Üzerine yaz', '"' + nm + '" adlı senaryo zaten var. Üzerine yazılsın mı?', 'Üzerine yaz'))) return;
    }
    try {
      const res = await api.post('/api/scenarios', { name: nm });
      toast('"' + res.name + '" kaydedildi (' + res.cells + ' hücre)', 'ok');
      name.value = '';
      await reload();
    } catch (err) { errorToast(err); }
  };
  save.addEventListener('click', doSave);
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSave(); });

  m.body.appendChild(h('p', { class: 'muted', style: { margin: '0 0 10px' } },
    'Senaryo = sayfalarda değiştirdiğiniz kişisel girdilerin (PPK adımları, valörler, hesaplayıcı girdileri …) tamamı. ',
    'Senaryolar isminizle saklanır; başka kullanıcılar sizinkileri görmez.'));
  m.body.appendChild(h('div', { style: { display: 'flex', gap: '8px', marginBottom: '14px' } }, name, save));
  m.body.appendChild(list);
  m.body.appendChild(h('div', { style: { height: '14px' } }));
  m.body.appendChild(mine);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  try { await reload(); } catch (err) { errorToast(err); }
  name.focus();
}
