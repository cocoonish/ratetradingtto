// Ajanda: what must not be forgotten - a day ("Bugün" with one click), maybe a time, the work, maybe a deadline; the
// desk's (everybody sees it, anybody ticks it off) or one's own.  An item may repeat ("Tekrar": every day, every business
// day of the desk's calendar, chosen days of the week, the month's last business day) at a time: each of its days is
// its own - ticked off for that day only - and the items themselves are listed under "Tekrarlayan işler", changed,
// paused and deleted there.  Deadlines not met (and a recurring item's day whose time passed) come first, then today,
// then the days ahead; the past (30 days) is folded.  The shell reminds of what is due (desk.js, agendaalarms.js); this
// page lists, adds, ticks off and deletes.  What is written goes on the page as text only.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, modal } from '../ui.js';
import { localDay, hhmm, dayTitle, shiftDay, stampText, isLate } from '../desk.js';
import { askPermission } from '../alarms.js';

const TR_DATE = (iso) => iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4);
/** how an item repeats: the server's names, as the page says them */
const REPEATS = [['once', 'Bir kez'], ['daily', 'Her gün'], ['workdays', 'Her iş günü'], ['weekdays', 'Seçili günler'],
  ['monthend', 'Ayın son iş günü']];
const WEEKDAYS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];          // 1-7, Monday first
const DOW = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];               // of Date.getDay()

function repeatSelect(id, value, once) {
  const s = h('select', { class: 'inp', id, title: 'Tekrar' });
  for (const [v, t] of REPEATS) if (once || v !== 'once') s.appendChild(h('option', { value: v }, t));
  s.value = value;
  return s;
}

/** "Pzt … Paz" tick boxes (``chosen``: the days 1-7 ticked); ``picked`` reads them back. */
function dayBoxes(id, chosen) {
  return h('span', { class: 'agenda-weekdays', id }, ...WEEKDAYS.map((t, i) => {
    const box = h('input', { type: 'checkbox', 'data-d': String(i + 1) });
    box.checked = (chosen || []).includes(i + 1);
    return h('label', { class: 'check' }, box, ' ' + t);
  }));
}
const picked = (boxes) => [...boxes.querySelectorAll('input[type=checkbox]')].filter((x) => x.checked).map((x) => Number(x.dataset.d));

/** "Bugün 10:00", "Yarın 08:30", "17.11.2026 Sal 10:00" */
function nextText(next, today) {
  const [y, m, d] = next.day.split('-').map(Number);
  const day = next.day === today ? 'Bugün' : (next.day === shiftDay(today, 1) ? 'Yarın'
    : TR_DATE(next.day) + ' ' + DOW[new Date(y, m - 1, d).getDay()]);
  return day + ' ' + next.time;
}

export class AgendaPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.items = [];
    this.rules = [];
    this.pastDays = 30;
    this.shared = true;
    this.reading = false;
    this.again = false;
    this.clock = null;
  }

  async load() {
    clear(this.host);
    // ---- a new item
    this.day = h('input', { class: 'inp', type: 'date', id: 'agenda-day', value: localDay(new Date()), title: 'Gün' });
    this.day.addEventListener('change', () => this.repeatChanged());
    const today = h('button', { class: 'btn sm', type: 'button', id: 'agenda-today', title: 'Bugünü seç' }, 'Bugün');
    today.addEventListener('click', () => { this.day.value = localDay(new Date()); this.repeatChanged(); this.text.focus(); });
    this.time = h('input', { class: 'inp', type: 'time', id: 'agenda-time', title: 'Saat (isteğe bağlı)' });
    this.text = h('input', { class: 'inp', type: 'text', id: 'agenda-text', maxlength: '300', placeholder: 'Unutulmaması gereken iş…' });
    this.text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); this.submit(); } });
    this.deadline = h('input', { type: 'checkbox', id: 'agenda-deadline' });
    this.scope = h('div', { class: 'seg', id: 'agenda-scope', title: 'Masa: herkes görür · Kişisel: yalnızca siz' },
      h('button', { type: 'button', class: 'on', 'data-v': 'shared' }, 'Masa'), h('button', { type: 'button', 'data-v': 'own' }, 'Kişisel'));
    this.scope.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      this.shared = b.dataset.v === 'shared';
      for (const x of this.scope.children) x.classList.toggle('on', x === b);
    });
    const add = h('button', { class: 'btn primary', type: 'button', id: 'agenda-add' }, 'Ekle');
    add.addEventListener('click', () => this.submit());
    // ---- how it repeats: once (the day above), or from that day on at the time
    this.repeat = repeatSelect('agenda-repeat', 'once', true);
    this.repeat.addEventListener('change', () => this.repeatChanged());
    this.weekdays = dayBoxes('agenda-weekdays', []);
    this.end = h('input', { class: 'inp', type: 'date', id: 'agenda-end', title: 'Bitiş günü (isteğe bağlı; boşsa süresiz)' });
    this.endBox = h('span', { class: 'agenda-end' }, h('span', { class: 'muted' }, 'Bitiş'), this.end);
    this.repeatHint = h('span', { class: 'muted agenda-repeat-hint' });
    const form = h('section', { class: 'panel wide' }, h('header', null, h('h2', null, 'Ajandaya ekle')),
      h('div', { class: 'agenda-form' }, this.day, today, this.time, this.text,
        h('label', { class: 'check', title: 'Son gün / son saat: yaklaşınca ve gelince ekranda uyarı' }, this.deadline, ' Deadline'),
        this.scope, add),
      h('div', { class: 'agenda-repeat', id: 'agenda-repeat-row' }, h('span', { class: 'muted' }, 'Tekrar'), this.repeat, this.weekdays,
        this.endBox, this.repeatHint),
      h('div', { class: 'note' }, 'Saati olan işte o saatte, deadline\'da 15 dakika önce de ekranda uyarı çıkar (saatsiz deadline\'da '
        + 'bir gün önce ve o gün); hangi sayfada olursanız olun. Tekrarlayan işin (Tekrar) saati olmalıdır: her günü ayrı tamamlanır, '
        + 'uyarısında "Ertele 10 dk" ve "Bugün tamam" vardır; dashboard kapalıyken saati geçen gün, açılınca gecikmiş görünür. '
        + '"Her iş günü" ve "Ayın son iş günü" hafta sonunu ve Ayarlar → Tatiller\'deki TRY tatillerini atlar. Masa işini herkes görür '
        + 've tamamlayabilir; silmek ve değiştirmek ekleyenin ya da bir yöneticinin işidir. Kişisel işi yalnızca siz görürsünüz.'));
    this.list = h('div', { class: 'agenda-list', id: 'agenda-list' });
    this.rulesBox = h('div', { class: 'agenda-rules', id: 'agenda-rules' });
    this.host.appendChild(h('div', { class: 'panels agenda-page' }, form,
      h('section', { class: 'panel wide' }, h('header', null, h('h2', null, 'Ajanda')), this.list),
      h('section', { class: 'panel wide' }, h('header', null, h('h2', null, 'Tekrarlayan işler')), this.rulesBox)));
    this.repeatChanged();
    await this.reload();
    if (!this.dead) this.clock = setInterval(() => this.render(), 30000);   // what is late changes as time goes by
  }

  /** The market's generations do not concern the agenda (its own news come through ``onDesk``). */
  refresh() { return Promise.resolve(); }

  /** The agenda changed - also while the page is still loading: then it reads once more when that is done. */
  onDesk(changed) {
    if (!changed.includes('agenda')) return;
    this.reload().catch((err) => { if (!err.network && err.status !== 401) errorToast(err); });
  }

  /** One reading at a time; a change meanwhile reads once more after it. */
  async reload() {
    if (this.reading) { this.again = true; return; }
    this.reading = true;
    try {
      do {
        this.again = false;
        this.take(await api.get('/api/agenda'));
      } while (this.again);
    } finally {
      this.reading = false;
    }
  }

  take(res) {
    if (this.dead) return;
    this.items = res.items;
    this.rules = res.rules || [];
    this.pastDays = res.past_days || this.pastDays;
    this.render();
    this.renderRules();
  }

  /** A recurring item: the day field is its first day (said beside it), the time is needed, its days of the week when
   * chosen. */
  repeatChanged() {
    const v = this.repeat.value;
    const on = v !== 'once';
    const start = this.day.value > localDay(new Date()) ? this.day.value : null;
    this.weekdays.classList.toggle('hidden', v !== 'weekdays');
    this.endBox.classList.toggle('hidden', !on);
    this.repeatHint.textContent = on ? (start ? 'başlangıç ' + TR_DATE(start) + ' (gün alanı)' : 'bugünden başlar')
      + ' · saat gerekli · her günü ayrı tamamlanır' : '';
    this.day.title = on ? 'Başlangıç günü (bugün ya da önceyse bugünden başlar)' : 'Gün';
    this.time.title = on ? 'Saat (gerekli: her gününde o saatte uyarır)' : 'Saat (isteğe bağlı)';
  }

  render() {
    const now = new Date();
    const today = localDay(now);
    const time = hhmm(now);
    const late = this.items.filter((it) => isLate(it, today, time));
    const rest = this.items.filter((it) => !isLate(it, today, time));
    const box = clear(this.list);
    if (late.length) {
      box.appendChild(this.group(late.every((it) => it.deadline) ? 'Gecikmiş deadline\'lar' : 'Gecikmiş işler', late, 'late', true));
    }
    box.appendChild(this.group('Bugün · ' + dayTitle(today), rest.filter((it) => it.day === today), 'today', false,
      'Bugün için iş yok.'));
    const ahead = new Map();
    for (const it of rest.filter((x) => x.day > today)) {
      if (!ahead.has(it.day)) ahead.set(it.day, []);
      ahead.get(it.day).push(it);
    }
    const tomorrow = shiftDay(today, 1);
    for (const [day, items] of ahead) box.appendChild(this.group((day === tomorrow ? 'Yarın · ' : '') + dayTitle(day), items, '', false));
    const past = rest.filter((it) => it.day < today);
    if (past.length) {
      const fold = h('details', { class: 'agenda-past', id: 'agenda-past', open: !!this.pastOpen },
        h('summary', null, 'Geçmiş (son ' + this.pastDays + ' gün) · ' + past.length + ' iş'));
      fold.addEventListener('toggle', () => { this.pastOpen = fold.open; });     // stays open when drawn again
      fold.appendChild(this.table(past.slice().reverse(), true));
      box.appendChild(fold);
    }
  }

  group(title, items, cls, withDay, empty) {
    const sec = h('section', { class: 'agenda-day' + (cls ? ' ' + cls : ''), dataset: { group: cls || 'day' } },
      h('h3', null, title, items.length ? h('span', { class: 'muted' }, ' · ' + items.length + ' iş') : null));
    sec.appendChild(items.length || !empty ? this.table(items, withDay) : this.table([], false, empty));
    return sec;
  }

  table(items, withDay, empty) {
    const body = h('tbody');
    if (!items.length && empty) body.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '5' }, empty)));
    for (const it of items) body.appendChild(this.row(it, withDay));
    return h('table', { class: 'plain agenda' }, body);
  }

  row(it, withDay) {
    const done = h('input', { type: 'checkbox', title: it.done ? 'Tamamlandı – geri almak için tıklayın'
      : (it.rule ? 'Bu günü tamamlandı olarak işaretle (diğer günleri değişmez)' : 'Tamamlandı olarak işaretle') });
    done.checked = it.done;
    done.addEventListener('change', () => this.mark(it, done.checked));
    const when = (withDay ? TR_DATE(it.day) + (it.time ? ' ' : '') : '') + (it.time || '');
    const what = h('td', { class: 'l what' }, h('span', { class: 'txt' }, it.text));
    if (it.rule) {
      what.appendChild(h('span', { class: 'desk-tag repeat', title: 'Tekrarlayan iş: her günü ayrı tamamlanır; değiştirmek, '
        + 'duraklatmak, silmek aşağıda Tekrarlayan işler\'de' }, '↻ ' + it.repeat));
    }
    if (it.deadline) what.appendChild(h('span', { class: 'desk-tag deadline' }, 'Deadline'));
    if (!it.shared) what.appendChild(h('span', { class: 'desk-tag' }, 'Kişisel'));
    const who = it.done ? '✓ ' + (it.done_by || '') + ' · ' + stampText(it.done_at) : it.by;
    const del = it.can_delete ? h('button', { class: 'iconbtn', type: 'button', title: 'Sil', onclick: () => this.remove(it) }, '✕') : null;
    const data = { id: String(it.id) };
    if (it.rule) data.rule = String(it.rule);
    return h('tr', { class: it.done ? 'done' : '', dataset: data },
      h('td', { class: 'l chk' }, done), h('td', { class: 'l when' }, when || '–'), what,
      h('td', { class: 'l who muted', title: 'Ekleyen: ' + it.by + ' · ' + stampText(it.at) }, who), h('td', { class: 'act' }, del));
  }

  // ---------------------------------------------------------------------- the recurring items
  renderRules() {
    const box = clear(this.rulesBox);
    if (!this.rules.length) {
      box.appendChild(h('div', { class: 'empty' }, 'Tekrarlayan iş yok. Eklemek için yukarıda "Tekrar"ı seçin: her gün, her iş günü, '
        + 'seçili günler ya da ayın son iş günü.'));
      return;
    }
    const today = localDay(new Date());
    const body = h('tbody');
    for (const r of this.rules) body.appendChild(this.ruleRow(r, today));
    box.appendChild(h('table', { class: 'plain agenda rules' },
      h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Ne zaman'), h('th', { class: 'l' }, 'İş'), h('th', { class: 'l' }, 'Sonraki'),
        h('th', { class: 'l' }, 'Ekleyen'), h('th'))), body));
  }

  ruleRow(r, today) {
    const span = [r.start ? 'başlangıç ' + TR_DATE(r.start) : '', r.end ? 'bitiş ' + TR_DATE(r.end) : ''].filter(Boolean).join(' · ');
    const when = h('td', { class: 'l when' }, h('b', null, r.time), ' ' + r.repeat_text, span ? h('div', { class: 'span muted' }, span) : null);
    const what = h('td', { class: 'l what' }, h('span', { class: 'txt' }, r.text));
    if (r.deadline) what.appendChild(h('span', { class: 'desk-tag deadline' }, 'Deadline'));
    if (!r.shared) what.appendChild(h('span', { class: 'desk-tag' }, 'Kişisel'));
    if (r.paused) {
      what.appendChild(h('span', { class: 'desk-tag paused', title: 'Duraklatan: ' + (r.paused_by || '') + ' · ' + stampText(r.paused_at) },
        'Duraklatıldı'));
    }
    const next = r.paused ? 'duraklatıldı' : (r.next ? nextText(r.next, today) : 'bitti');
    const act = h('td', { class: 'act' });
    if (r.can_edit) {
      act.appendChild(h('button', { class: 'btn sm rule-edit', type: 'button', title: 'Tekrarı, saati, işi, günleri değiştir',
        onclick: () => this.editRule(r) }, 'Düzenle'));
      act.appendChild(h('button', { class: 'btn sm rule-pause', type: 'button',
        title: r.paused ? 'Yeniden başlat (bugünden, şimdiden sonrası sayılır)' : 'Duraklat: devam ettirilene kadar günü olmaz, uyarmaz',
        onclick: () => this.pauseRule(r, !r.paused) }, r.paused ? 'Devam et' : 'Duraklat'));
      act.appendChild(h('button', { class: 'iconbtn rule-del', type: 'button', title: 'Sil', onclick: () => this.removeRule(r) }, '✕'));
    }
    return h('tr', { class: r.paused ? 'paused' : '', dataset: { rule: String(r.id) } }, when, what, h('td', { class: 'l next' }, next),
      h('td', { class: 'l who muted', title: 'Ekleyen: ' + r.by + ' · ' + stampText(r.at) }, r.by), act);
  }

  /** A recurring item changed: how it repeats, its time, its work, its days; who it is for stays. */
  editRule(r) {
    const m = modal({ title: 'Tekrarlayan işi düzenle', width: 600 });
    const repeat = repeatSelect('rule-repeat', r.repeat, false);
    const days = dayBoxes('rule-days', r.weekdays);
    const time = h('input', { class: 'inp', type: 'time', id: 'rule-time', value: r.time });
    const text = h('input', { class: 'inp', type: 'text', id: 'rule-text', maxlength: '300', value: r.text });
    const deadline = h('input', { type: 'checkbox', id: 'rule-deadline' });
    deadline.checked = r.deadline;
    const start = h('input', { class: 'inp', type: 'date', id: 'rule-start', value: r.start || '' });
    const end = h('input', { class: 'inp', type: 'date', id: 'rule-end', value: r.end || '' });
    const err = h('div', { class: 'errtxt' });
    const field = (label, el) => h('div', { class: 'field' }, h('label', null, label), el);
    const daysField = field('Günler', days);
    const showDays = () => daysField.classList.toggle('hidden', repeat.value !== 'weekdays');
    repeat.addEventListener('change', showDays);
    showDays();
    m.body.appendChild(h('div', { class: 'rule-form' },
      h('div', { class: 'row' }, field('Tekrar', repeat), field('Saat', time),
        h('label', { class: 'check', title: 'Son saat: 15 dakika önce ve saatinde uyarı; tamamlanmazsa gecikmiş kalır' }, deadline, ' Deadline')),
      daysField, field('İş', text),
      h('div', { class: 'row' }, field('Başlangıç (isteğe bağlı)', start), field('Bitiş (isteğe bağlı)', end)),
      h('div', { class: 'muted' }, (r.shared ? 'Masa işi: herkes görür.' : 'Kişisel iş: yalnızca siz görürsünüz.')
        + ' Kimin için olduğu sonradan değişmez. Yeni saat ya da tekrar şimdiden sonrası için geçerlidir.'), err));
    const save = h('button', { class: 'btn primary', type: 'button', id: 'rule-save' }, 'Kaydet');
    save.addEventListener('click', async () => {
      const body = { repeat: repeat.value, time: time.value || null, text: text.value, deadline: deadline.checked,
        weekdays: picked(days), start: start.value || null, end: end.value || null };
      if (!body.time) { err.textContent = 'Saat gerekli'; time.focus(); return; }
      if (!body.text.trim()) { err.textContent = 'İşi yazın'; text.focus(); return; }
      if (body.repeat === 'weekdays' && !body.weekdays.length) { err.textContent = 'En az bir gün seçin'; return; }
      save.disabled = true;
      try {
        this.take(await api.post('/api/agenda/rules/' + r.id, body));
        m.close();
        toast('Tekrarlayan iş kaydedildi', 'ok', 2200);
      } catch (e) {
        err.textContent = e.message;
        save.disabled = false;
      }
    });
    text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); save.click(); } });
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(save);
    text.focus();
  }

  async pauseRule(r, paused) {
    try {
      this.take(await api.post('/api/agenda/rules/' + r.id + '/pause', { paused }));
      toast(paused ? 'Duraklatıldı: devam ettirilene kadar uyarmaz' : 'Devam ediyor: ' + r.repeat_text + ' ' + r.time, 'ok', 2600);
    } catch (err) { errorToast(err); }
  }

  async removeRule(r) {
    if (!(await confirmDialog('Tekrarlayan işi sil', '“' + r.text + '” (' + r.repeat_text + ' ' + r.time + ') ve günlerinin tamamlanma '
      + 'kayıtları silinsin mi?', 'Sil', true))) return;
    try { this.take(await api.del('/api/agenda/rules/' + r.id)); } catch (err) { errorToast(err); }
  }

  // ---------------------------------------------------------------------- adding, ticking off, deleting
  async submit() {
    if (this.adding) return;                         // one at a time: a double click adds the item once
    if (this.repeat.value !== 'once') { await this.submitRule(); return; }
    const body = { day: this.day.value, time: this.time.value || null, text: this.text.value, deadline: this.deadline.checked,
      shared: this.shared };
    if (!body.day) { toast('Gün seçin', 'err'); this.day.focus(); return; }
    if (!body.text.trim()) { toast('İşi yazın', 'err'); this.text.focus(); return; }
    this.adding = true;
    try {
      this.take(await api.post('/api/agenda', body));
      if (this.dead) return;
      // emptied for the next item - unless the next one is already being typed
      if (this.text.value === body.text) this.text.value = '';
      if ((this.time.value || null) === body.time) this.time.value = '';
      if (this.deadline.checked === body.deadline) this.deadline.checked = false;
      this.text.focus();
      toast('Ajandaya eklendi: ' + TR_DATE(body.day) + (body.time ? ' ' + body.time : ''), 'ok', 2200);
    } catch (err) {
      errorToast(err);
    } finally {
      this.adding = false;
    }
  }

  /** A recurring item: from the day chosen (when it is after today) at the time, until the last day if one is given. */
  async submitRule() {
    const today = localDay(new Date());
    const body = { repeat: this.repeat.value, time: this.time.value || null, text: this.text.value, deadline: this.deadline.checked,
      shared: this.shared, weekdays: picked(this.weekdays), start: this.day.value > today ? this.day.value : null,
      end: this.end.value || null };
    if (!body.time) { toast('Tekrarlayan iş için saat seçin', 'err'); this.time.focus(); return; }
    if (!body.text.trim()) { toast('İşi yazın', 'err'); this.text.focus(); return; }
    if (body.repeat === 'weekdays' && !body.weekdays.length) { toast('En az bir gün seçin', 'err'); return; }
    this.adding = true;
    try {
      const res = await api.post('/api/agenda/rules', body);
      askPermission();                               // the browser's notifications: asked once (a click is needed to ask)
      this.take(res);
      if (this.dead) return;
      // emptied for the next item - a single one unless chosen again - unless the next one is already being typed
      if (this.text.value === body.text) this.text.value = '';
      if ((this.time.value || null) === body.time) this.time.value = '';
      if (this.deadline.checked === body.deadline) this.deadline.checked = false;
      if (this.repeat.value === body.repeat) this.repeat.value = 'once';
      if ((this.end.value || null) === body.end) this.end.value = '';
      this.repeatChanged();
      this.text.focus();
      toast('Tekrarlayan iş eklendi: ' + REPEATS.find(([v]) => v === body.repeat)[1] + ' ' + body.time
        + (body.start ? ' · başlangıç ' + TR_DATE(body.start) : ''), 'ok', 3000);
    } catch (err) {
      errorToast(err);
    } finally {
      this.adding = false;
    }
  }

  async mark(it, done) {
    const asked = it.rule ? api.post('/api/agenda/rules/' + it.rule + '/done', { day: it.day, done })
      : api.post('/api/agenda/' + it.id, { done });
    try { this.take(await asked); } catch (err) { errorToast(err); this.render(); }
  }

  async remove(it) {
    if (!(await confirmDialog('İşi sil', '“' + it.text + '” ajandadan silinsin mi?', 'Sil', true))) return;
    try { this.take(await api.del('/api/agenda/' + it.id)); } catch (err) { errorToast(err); }
  }

  destroy() {
    this.dead = true;
    if (this.clock) clearInterval(this.clock);
  }
}
