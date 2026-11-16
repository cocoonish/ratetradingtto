// Günlük İşlemler: what fills the entry form from elsewhere - the templates ("Şablonlar") and rows pasted from Excel
// ("Excel'den yapıştır").  The form itself, and ``fillForm`` / ``formSpec`` (the one way into it and out of it), are
// blotter.js's: a template is a spec of ``fillForm``.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, promptDialog, modal, debounce } from '../ui.js';
import { num, pct, serialDate } from '../format.js';

export const KIND_SHORT = { fwd: 'FX', ois: 'OIS', bond: 'Tahvil' };
const KIND_LONG = { fwd: 'FX Forward', ois: 'OIS', bond: 'Tahvil' };
const BASIS_TEXT = { RET_BID: 'RET bid', RET_MID: 'RET mid', RET_ASK: 'RET ask', TRY: 'TRY faizi', FWD: 'Forward kur', SP: 'Swap puanı' };
const STRATEGY_TEXT = { outright: 'Outright', spread: 'Spread', fly: 'Fly', fra: 'FRA', mpc: 'MPC' };
const monthText = (m) => (m === 0 ? 'Spot' : (m % 12 === 0 ? (m / 12) + 'Y' : m + 'M'));

const SPEC_ORDER = { fwd: ['pair', 'dir', 'amount', 'quote_amount', 'date', 'basis', 'spot', 'cpt', 'note'],
  ois: ['strategy', 'side', 'tenors', 'months', 'mpc', 'level', 'size', 'cpt', 'note'], bond: ['dir', 'instrument', 'amount', 'price', 'note'] };
const SPEC_WORD = { date: 'valör ', spot: 'spot ', level: '@ ', price: '@ ', note: 'not: ' };

/** One field of a spec as the desk says it (a forward's amounts with their currencies, by the spec's pair). */
function specValue(s, k) {
  const v = s[k];
  if (v === undefined || v === null || v === '') return '';
  const pair = s.pair || '';
  switch (k) {
    case 'dir': return v === 'B' ? 'Alış' : 'Satış';
    case 'amount': return s.kind === 'fwd' && pair ? v + ' ' + pair.slice(0, 3) : String(v);
    case 'quote_amount': return v + ' ' + (pair ? pair.slice(3) : 'karşı para') + ' ✎';
    case 'basis': return (BASIS_TEXT[v] || v) + (s.value ? ' ' + s.value : '');
    case 'strategy': return STRATEGY_TEXT[v] || v;
    case 'tenors': return v.join('/');
    case 'months': return v.map(monthText).join('→');
    case 'mpc': return (v[0] ? 'MPC' + v[0] : 'Spot') + '→MPC' + v[1];
    case 'size': return v + (s.sizeMode === 'nominal' ? ' TL' : ' $/bp');
    case 'value': case 'sizeMode': case 'kind': return '';           // (with their basis, their size)
    default: return String(v);
  }
}

/** A template's spec in words: what one click fills the form with. */
export function describeSpec(s) {
  return (SPEC_ORDER[s.kind] || []).map((k) => { const t = specValue(s, k); return t ? (SPEC_WORD[k] || '') + t : ''; }).filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------------------------------------- templates
// what of a form a template can keep: [label, the spec's keys, ticked unless the user unticks it]
const PARTS = {
  fwd: [['Parite', ['pair'], true], ['Yön', ['dir'], true], ['Tutar', ['amount', 'quote_amount'], true], ['Valör', ['date'], true],
    ['Fiyatlama', ['basis', 'value'], true], ['Spot', ['spot'], true], ['Karşı taraf', ['cpt'], true], ['Not', ['note'], false]],
  ois: [['Strateji', ['strategy'], true], ['Yön', ['side'], true], ['Vadeler / tarihler', ['tenors', 'months', 'mpc'], true],
    ['Seviye', ['level'], false], ['Büyüklük', ['size', 'sizeMode'], true], ['Karşı taraf', ['cpt'], true], ['Not', ['note'], false]],
  bond: [['Yön', ['dir'], true], ['Enstrüman', ['instrument'], true], ['Tutar', ['amount'], true], ['Fiyat', ['price'], false],
    ['Not', ['note'], false]],
};

/** The strip above the entry form: a template is one click away; "+ Şablon olarak kaydet", "Yönet…". */
export function renderTemplates(page, force) {
  const bar = page.tplBar;
  const list = (page.data && page.data.templates) || [];
  const key = JSON.stringify(list);
  if (page.tplKey === key && !force) return;               // as it was: left alone
  page.tplKey = key;
  clear(bar);
  bar.appendChild(h('span', { class: 'lbl' }, 'Şablonlar'));
  for (const t of list) {
    const b = h('button', { type: 'button', class: 'chip' + (t.shared ? ' shared' : ''), 'data-id': String(t.id),
      title: describeSpec(t.spec) + (t.shared ? '\nMasa şablonu · ' + t.by : '') + '\nTıklayınca form dolar; işlem kaydedilmez' },
    h('span', { class: 'k' }, KIND_SHORT[t.kind] || t.kind), t.name);
    b.addEventListener('click', () => page.applyTemplate(t));
    bar.appendChild(b);
  }
  if (!list.length) bar.appendChild(h('span', { class: 'muted' }, 'yok – formu doldurup kaydedin'));
  bar.appendChild(h('span', { class: 'grow' }));
  const save = h('button', { class: 'btn sm ghost', type: 'button', id: 'tpl-save',
    title: 'Formda olanı (seçtiğiniz alanlarla) adıyla saklayın: bir tıkla form yeniden dolar' }, '+ Şablon olarak kaydet');
  save.addEventListener('click', () => templateDialog(page, null));
  bar.appendChild(save);
  if (list.length) {
    const manage = h('button', { class: 'btn sm ghost', type: 'button', id: 'tpl-manage', title: 'Şablonları yeniden adlandır, formdakiyle güncelle, sil' }, 'Yönet…');
    manage.addEventListener('click', () => manageTemplates(page));
    bar.appendChild(manage);
  }
}

function takeTemplates(page, res) {
  page.data.templates = res.templates;
  page.data.can_publish = res.can_publish;
  renderTemplates(page, true);
}

/** "Şablon olarak kaydet": the form of the tab on screen, the fields to keep ticked (any subset), a name - one's own, or
 * the desk's for an administrator.  ``t``: a template to put the form's fields into instead of a new one. */
export function templateDialog(page, t) {
  const kind = t ? t.kind : page.tab;
  if (!PARTS[kind]) return null;
  const spec = page.formSpec(kind);
  const m = modal({ title: t ? 'Şablonu güncelle · ' + t.name : 'Şablon olarak kaydet · ' + KIND_LONG[kind], width: 500 });
  m.box.id = 'tpl-dialog';
  const name = h('input', { class: 'inp', id: 'tpl-name', maxlength: '60', placeholder: 'örn. Garanti USDTRY 3A satış', style: { width: '100%' } });
  name.value = t ? t.name : '';
  const parts = h('div', { class: 'tplparts', id: 'tpl-parts' });
  const ticks = [];
  for (const [label, keys, on] of PARTS[kind]) {
    const have = keys.some((k) => spec[k] !== undefined);
    const box = h('input', { type: 'checkbox', 'data-part': keys[0] });
    box.checked = have && (t ? keys.some((k) => t.spec[k] !== undefined) : on);
    box.disabled = !have;
    ticks.push([box, keys]);
    const value = keys.map((k) => specValue(spec, k)).filter(Boolean).join(' ');
    parts.appendChild(h('label', { class: 'check' }, box, ' ' + label + ' ', h('span', { class: 'muted' }, have ? value || '✓' : '(formda boş)')));
  }
  let scope = t && t.shared ? 'desk' : 'mine';
  const scopeBox = h('div', { class: 'tplscope' });
  if (page.data.can_publish) {
    const s = h('div', { class: 'seg', id: 'tpl-scope' });
    for (const [v, label] of [['mine', 'Kişisel'], ['desk', 'Masa (herkes görür)']]) {
      const b = h('button', { type: 'button', class: v === scope ? 'on' : '' }, label);
      b.dataset.v = v;
      b.addEventListener('click', () => { scope = v; for (const x of s.children) x.classList.toggle('on', x.dataset.v === v); });
      s.appendChild(b);
    }
    scopeBox.appendChild(h('div', { class: 'field' }, h('label', null, 'Kimin'), s));
  } else {
    scopeBox.appendChild(h('div', { class: 'muted' }, 'Kişisel şablon: yalnızca siz görürsünüz (masa şablonlarını yöneticiler yayımlar).'));
  }
  m.body.appendChild(h('div', { class: 'field' }, h('label', { for: 'tpl-name' }, 'Ad'), name));
  m.body.appendChild(h('div', { class: 'field', style: { marginTop: '10px' } }, h('label', null, 'Şablonda kalacak alanlar'), parts));
  m.body.appendChild(scopeBox);
  m.body.appendChild(h('div', { class: 'muted', style: { marginTop: '8px' } }, 'Şablon formu doldurur, işlem kaydetmez. Tutar yazıldığı dövizle saklanır; '
    + 'valöre vade (3M) yazıldıysa her seferinde günün spotundan hesaplanır.'));
  const ok = h('button', { class: 'btn primary', type: 'button', id: 'tpl-ok' }, t ? 'Güncelle' : 'Kaydet');
  const submit = async () => {
    const chosen = { kind };
    for (const [box, keys] of ticks) if (box.checked) for (const k of keys) if (spec[k] !== undefined) chosen[k] = spec[k];
    // a side and the legs belong to their strategy
    if (kind === 'ois' && ['side', 'tenors', 'months', 'mpc'].some((k) => chosen[k] !== undefined)) chosen.strategy = spec.strategy;
    if (!name.value.trim()) { toast('Şablona bir ad verin', 'err'); name.focus(); return; }
    if (Object.keys(chosen).length === 1) { toast('Şablonda kalacak en az bir alan seçin', 'err'); return; }
    ok.disabled = true;
    try {
      const body = { name: name.value, kind, spec: chosen, shared: scope === 'desk' };
      const res = t ? await api.post('/api/blotter/templates/' + t.id, body) : await api.post('/api/blotter/templates', body);
      takeTemplates(page, res);
      toast('Şablon ' + (t ? 'güncellendi' : 'kaydedildi') + ': ' + name.value.trim(), 'ok', 2600);
      m.close();
    } catch (err) { errorToast(err); ok.disabled = false; }
  };
  ok.addEventListener('click', submit);
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(ok);
  name.focus();
  return m;
}

/** "Yönet…": every template the user fills the form from - fill it, rename it, put the form into it, delete it (the
 * desk's: an administrator). */
export function manageTemplates(page) {
  const m = modal({ title: 'Şablonlar', width: 900 });
  m.box.id = 'tpl-manage-dialog';
  const body = h('div');
  const render = () => {
    clear(body);
    const list = page.data.templates || [];
    if (!list.length) { body.appendChild(h('div', { class: 'muted' }, 'Şablon yok.')); return; }
    const table = h('table', { class: 'plain tpltable', id: 'tpl-list' }, h('tr', null, h('th', { class: 'l' }, 'Ad'), h('th', { class: 'l' }, 'Ürün'),
      h('th', { class: 'l' }, 'Kimin'), h('th', { class: 'l' }, 'İçerik'), h('th', null, '')));
    for (const t of list) {
      const acts = h('td', { class: 'acts' });
      const act = (label, title, id, fn) => {
        const b = h('button', { class: 'btn sm', type: 'button', title, id }, label);
        b.addEventListener('click', fn);
        acts.appendChild(b);
      };
      act('Doldur', 'Formu bu şablonla doldur', 'tpl-fill-' + t.id, () => { m.close(); page.applyTemplate(t); });
      if (t.can_edit) {
        act('Adını değiştir', 'Yalnızca adı değişir', 'tpl-rename-' + t.id, async () => {
          const name = await promptDialog('Şablonun adı', 'Ad', t.name);
          if (!name || name === t.name) return;
          try {
            takeTemplates(page, await api.post('/api/blotter/templates/' + t.id, { name }));
            render();
          } catch (err) { errorToast(err); }
        });
        act('Formdakiyle güncelle', 'Şablonun içeriği ' + KIND_LONG[t.kind] + ' formunda şu an olanla değişir: önce formu düzenleyin', 'tpl-update-' + t.id, () => {
          m.close();
          if (page.tab !== t.kind) page.showTab(t.kind);
          templateDialog(page, t);
        });
        act('Sil', t.shared ? 'Masa şablonu herkesten kalkar' : 'Şablonu sil', 'tpl-delete-' + t.id, async () => {
          if (!(await confirmDialog('Şablonu sil', '"' + t.name + '" silinsin mi?' + (t.shared ? ' Masa şablonudur: herkesten kalkar.' : ''), 'Sil', true))) return;
          try {
            takeTemplates(page, await api.del('/api/blotter/templates/' + t.id));
            render();
          } catch (err) { errorToast(err); }
        });
      }
      table.appendChild(h('tr', { 'data-id': String(t.id) }, h('td', { class: 'l' }, h('b', null, t.name)), h('td', { class: 'l' }, KIND_LONG[t.kind] || t.kind),
        h('td', { class: 'l' }, t.shared ? 'Masa · ' + t.by : 'Kişisel'), h('td', { class: 'l desc' }, describeSpec(t.spec)), acts));
    }
    body.appendChild(table);
  };
  render();
  m.body.appendChild(body);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  return m;
}

// ---------------------------------------------------------------------------------------------- rows pasted from Excel
const BULK_EXAMPLE = {
  fwd: 'Excel\'den kopyalanan satırları yapıştırın (sekmeyle ayrılmış). Başlık satırı varsa tanınır:\n\n'
    + 'Yön\tTutar\tFaiz\tValör\nB\t10.000.000\t35,00%\t15.12.2026\nS\t5m\t35,10\t3M\n\n'
    + 'Başlık yoksa sütunlar Günlük İşlemler sayfasının listesi gibi okunur: Yön · Tutar · Faiz · Valör',
  ois: 'Excel\'den kopyalanan satırları yapıştırın (sekmeyle ayrılmış). Başlık satırı varsa tanınır:\n\n'
    + 'Nominal\tDV01 USD\tYön\tFaiz\tValör\tCPT\n\t1.000\tB\t35,55%\t1Y\tBARX\n\n'
    + 'Başlık yoksa sütunlar Günlük İşlemler sayfasının OIS listesi gibi okunur: Nominal · DV01 USD · Yön (B pay / S receive) · Faiz · Vade · CPT',
  bond: 'Excel\'den kopyalanan satırları yapıştırın (sekmeyle ayrılmış):\n\nEnstrüman\tTutar\tFiyat\nTRT150328T24\t50.000.000\t98,25\n'
    + 'TRT150328T24\t-20.000.000\t98,75\n\nTutar + alış / − satış (ya da Yön sütunu)',
};

function tsvLine(cells) {
  return cells.map((c) => (/[\t\n"]/.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c)).join('\t');
}

function signed(v) {
  return typeof v === 'number' ? (v > 0 ? '+' : '') + num(v, 0) : '—';
}

/** A valid pasted row as it will be kept: what the form would show for it. */
function rowText(kind, t) {
  if (kind === 'fwd') {
    const base = t.pair.slice(0, 3), quote = t.pair.slice(3);
    return t.pair + ' ' + (t.dir === 'B' ? 'alış ' : 'satış ') + num(t.amount, 0) + ' ' + base
      + (t.typed === 'quote' ? ' (' + num(t.tl, 2) + ' ' + quote + ' ✎)' : '') + ' · ' + serialDate(t.value_date) + ' · forward ' + num(t.forward, 4)
      + (typeof t.try_rate === 'number' ? ' · TRY ' + pct(t.try_rate, 2) : '') + ' · DV01 ' + signed(t.dv01) + ' $';
  }
  if (kind === 'ois') {
    return t.label + ' · ' + t.legs.map((lg) => num(lg.nominal, 0) + ' TL').join(' / ') + ' · DV01 ' + signed(t.dv01.net) + ' $';
  }
  return (t.amount >= 0 ? 'Alış ' : 'Satış ') + (t.name || t.instrument) + ' ' + num(Math.abs(t.amount), 0) + ' @ ' + num(t.price, 3)
    + (typeof t.dv01 === 'number' ? ' · DV01 ' + signed(t.dv01) + ' $' : ' · DV01 bilinmiyor');
}

/** "Excel'den yapıştır": trades copied from Excel - read, mapped to the form's fields, each checked as the form checks it
 * (the preview), then the valid ones kept together, in one go.  A row with an error is never kept: after the save it stays
 * in the box (with the header) to be fixed. */
export function openBulk(page) {
  const st = page.bulk || (page.bulk = { kind: 'fwd', text: '', mapping: null, header: null, preview: null, previewed: null, seq: 0 });
  try { const k = localStorage.getItem('tto.blotter.bulk'); if (KIND_LONG[k] && !st.text) st.kind = k; } catch (e) { /* ignore */ }
  const m = modal({ title: 'Excel\'den toplu işlem girişi', width: 1100, onClose: () => { run.cancel(); } });
  m.box.id = 'bulk-dialog';
  const text = h('textarea', { id: 'bulk-text', class: 'inp chatbox', rows: '8', spellcheck: 'false', autocomplete: 'off' });
  text.value = st.text;
  const kindSeg = h('div', { class: 'seg', id: 'bulk-kind' });
  for (const [v, label] of [['fwd', 'FX Forward'], ['ois', 'OIS'], ['bond', 'Tahvil']]) {
    const b = h('button', { type: 'button' }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => {
      st.kind = v;
      st.mapping = null;
      st.header = null;
      try { localStorage.setItem('tto.blotter.bulk', v); } catch (e) { /* ignore */ }
      showKind();
      run();
    });
    kindSeg.appendChild(b);
  }
  const showKind = () => {
    for (const b of kindSeg.children) b.classList.toggle('on', b.dataset.v === st.kind);
    text.placeholder = BULK_EXAMPLE[st.kind];
  };
  const headBox = h('input', { type: 'checkbox', id: 'bulk-header' });
  headBox.addEventListener('change', () => { st.header = headBox.checked; st.mapping = null; run(); });
  const auto = h('button', { class: 'btn sm', type: 'button', id: 'bulk-auto', title: 'Sütunları yeniden başlıktan (yoksa Günlük İşlemler listelerinin sırasından) eşle' },
    'Otomatik eşle');
  auto.addEventListener('click', () => { st.mapping = null; st.header = null; run(); });
  const problems = h('div', { class: 'errtxt', id: 'bulk-problems' });
  const box = h('div', { class: 'bulkpreview', id: 'bulk-preview' });
  const summary = h('span', { class: 'muted', id: 'bulk-summary' });
  const saveBtn = h('button', { class: 'btn primary', type: 'button', id: 'bulk-save', disabled: true }, 'Kaydet');
  const clearBtn = h('button', { class: 'btn', type: 'button', id: 'bulk-clear' }, 'Temizle');
  clearBtn.addEventListener('click', () => { text.value = ''; st.text = ''; st.mapping = null; st.header = null; run(); text.focus(); });

  const render = () => {
    const p = st.preview;
    clear(box);
    clear(problems);
    summary.className = 'muted';
    summary.textContent = '';
    const fresh = p && st.previewed === text.value;
    saveBtn.disabled = !(fresh && p.valid);
    saveBtn.textContent = p && p.valid ? p.valid + ' satırı kaydet' : 'Kaydet';
    if (!p) return;
    if (p.error) { problems.textContent = p.error; return; }
    headBox.checked = !!p.header;
    if (p.problems && p.problems.length) problems.textContent = 'Sütunlar: ' + p.problems.join(' · ');
    if (!p.rows.length) { summary.textContent = text.value.trim() ? 'Okunacak satır yok' : ''; return; }
    const table = h('table', { class: 'plain bulk' });
    // the mapping: what each pasted column is
    const map = h('tr', { class: 'map' }, h('th', null, '#'), h('th', { class: 'l' }, 'Durum'));
    for (const col of p.columns) {
      const sel = h('select', { class: 'inp', 'data-col': String(col.i), title: (col.title ? 'Başlık: ' + col.title : (col.i + 1) + '. sütun')
        + (col.ccy ? ' · tutarın dövizi ' + col.ccy + ' (satırın paritesine göre döviz ya da karşı tutar)' : '') });
      sel.appendChild(h('option', { value: '' }, '— (yok say)'));
      for (const [k, label] of p.fields) sel.appendChild(h('option', { value: k }, label + (col.ccy && (k === 'amount' || k === 'quote_amount') ? ' · ' + col.ccy : '')));
      sel.value = col.field || '';
      sel.addEventListener('change', () => {
        st.mapping = [...table.querySelectorAll('tr.map select')].map((x) => x.value || null);
        run();
      });
      map.appendChild(h('th', { class: 'l' }, sel));
    }
    table.appendChild(map);
    if (p.head) table.appendChild(h('tr', { class: 'head' }, h('td', null, '1'), h('td', { class: 'l' }, 'başlık'), p.head.map((c) => h('td', { class: 'l' }, c))));
    for (const r of p.rows) {
      const st1 = r.ok ? h('td', { class: 'l st', title: rowText(p.kind, r.trade) }, '✓ ' + rowText(p.kind, r.trade)) : h('td', { class: 'l st', title: r.error }, '✕ ' + r.error);
      table.appendChild(h('tr', { class: 'line ' + (r.ok ? 'good' : 'bad'), 'data-n': String(r.n) }, h('td', null, String(r.n)), st1,
        r.cells.map((c) => h('td', { class: 'l cell' }, c))));
    }
    box.appendChild(table);
    summary.textContent = p.rows.length + ' satır · ' + p.valid + ' geçerli' + (p.invalid ? ' · ' + p.invalid + ' hatalı – hatalı satır kaydedilmez, kutuda kalır' : '');
    if (p.invalid) summary.className = 'warn-text';
  };

  const run = debounce(async () => {
    st.text = text.value;
    const seq = ++st.seq;
    if (!text.value.trim()) { st.preview = null; st.previewed = null; render(); return; }
    saveBtn.disabled = true;
    try {
      const res = await api.post('/api/blotter/bulk/preview', { kind: st.kind, text: text.value, mapping: st.mapping, header: st.header });
      if (seq !== st.seq) return;
      st.preview = res;
      st.previewed = text.value;
    } catch (err) {
      if (seq !== st.seq) return;
      st.preview = { error: err.message, rows: [] };
      st.previewed = null;
    }
    render();
  }, 300);
  const firstLine = (s) => (s || '').split('\n')[0];
  text.addEventListener('input', () => {
    // another paste (its first line is not the one read): its columns are read afresh
    if (firstLine(text.value) !== firstLine(st.previewed)) { st.mapping = null; st.header = null; }
    saveBtn.disabled = true;
    run();
  });

  saveBtn.addEventListener('click', async () => {
    const p = st.preview;
    if (!p || !p.valid || st.previewed !== text.value) return;
    saveBtn.disabled = true;
    try {
      const res = await api.post('/api/blotter/bulk', { kind: st.kind, text: st.previewed, mapping: st.mapping, header: st.header,
        rows: p.rows.filter((r) => r.ok).map((r) => r.n) });
      // what was not kept stays in the box, under its header, to be fixed
      const left = p.rows.filter((r) => res.left.includes(r.n));
      text.value = left.length ? (p.head ? [tsvLine(p.head)] : []).concat(left.map((r) => tsvLine(r.cells))).join('\n') : '';
      st.text = text.value;
      toast(res.saved + ' işlem kaydedildi' + (left.length ? ' · ' + left.length + ' hatalı satır kaydedilmedi: kutuda bırakıldı' : ''), left.length ? 'warn' : 'ok', 5000);
      page.ctx.refreshNow();
      if (!left.length) { st.preview = null; st.previewed = null; m.close(); return; }
      run();
    } catch (err) {
      errorToast(err);
      if (err.data && err.data.preview) { st.preview = err.data.preview; st.previewed = text.value; render(); }       // what it is now
      else render();
    }
  });

  m.body.appendChild(h('div', { class: 'bulkhead' }, h('div', { class: 'field' }, h('label', null, 'Ürün'), kindSeg),
    h('label', { class: 'check', title: 'İlk satır sütun başlıklarıysa (otomatik tanınır)' }, headBox, ' İlk satır başlık'), auto,
    h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Sayılar sizin biçiminizde okunur (Türkçe: 1.000.000,50 · İngilizce: 1,000,000.50); tarih gg.aa.yyyy ya da vade (3M)')));
  m.body.appendChild(text);
  m.body.appendChild(problems);
  m.body.appendChild(box);
  m.body.appendChild(h('details', { class: 'chathelp' }, h('summary', null, 'Sütunlar nasıl okunur?'),
    h('div', { class: 'muted pad0' }, 'Her satır formdaki gibi denetlenir ve fiyatlanır; geçerli satırlar tek seferde (hepsi ya da hiçbiri) kaydedilir. '
      + 'Başlık satırı tanınır: Günlük İşlemler sayfasının başlıkları (Yön, Tutar, Faiz, Valör · Nominal, DV01 USD, Faiz, Valör, CPT · Enstrüman, Tutar, Fiyat), '
      + 'bu sayfanın sütun adları ve İngilizceleri (Side, Amount, Value Date, Rate …). Forward\'da tutar başlığı bir döviz söylüyorsa (USD tutarı, TRY, Tutar (TL)) '
      + 'satırın paritesine göre döviz ya da karşı tutardır: TRY tutarı yazılan USDTRY satırının USD\'si forward kurundan hesaplanır. Fiyat: TRY faizi, forward kur ya da '
      + 'swap puanı sütunlarından biri; birden çoksa Fiyatlama sütunu (RET mid, TRY faizi, Forward kur, Swap puanı) hangisi olduğunu söyler. '
      + 'OIS satırı vadeyle (1Y) ya da Başlangıç / Bitiş tarihleriyle (MPC) girilir; nominal yazılmışsa DV01 ondan hesaplanır. Her sütunun ne olduğu üstteki seçimle değiştirilebilir.')));
  m.foot.appendChild(summary);
  m.foot.appendChild(h('span', { class: 'grow' }));
  m.foot.appendChild(clearBtn);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  m.foot.appendChild(saveBtn);
  showKind();
  if (st.preview && st.previewed === text.value) render(); else run();
  text.focus();
  return m;
}
