// Ajanda: what must not be forgotten - a day ("Bugün" with one click), maybe a time, the work, maybe a deadline; the
// desk's (everybody sees it, anybody ticks it off) or one's own.  Deadlines not met come first, then today, then the
// days ahead; the past (30 days) is folded.  The shell reminds of what is due (desk.js); this page lists, adds, ticks
// off and deletes.  What is written goes on the page as text only.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog } from '../ui.js';
import { localDay, hhmm, dayTitle, shiftDay, stampText, isLate } from '../desk.js';

const TR_DATE = (iso) => iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4);

export class AgendaPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.items = [];
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
    const today = h('button', { class: 'btn sm', type: 'button', id: 'agenda-today', title: 'Bugünü seç' }, 'Bugün');
    today.addEventListener('click', () => { this.day.value = localDay(new Date()); this.text.focus(); });
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
    const form = h('section', { class: 'panel wide' }, h('header', null, h('h2', null, 'Ajandaya ekle')),
      h('div', { class: 'agenda-form' }, this.day, today, this.time, this.text,
        h('label', { class: 'check', title: 'Son gün / son saat: yaklaşınca ve gelince ekranda uyarı' }, this.deadline, ' Deadline'),
        this.scope, add),
      h('div', { class: 'note' }, 'Saati olan işte o saatte, deadline\'da 15 dakika önce de ekranda uyarı çıkar (saatsiz deadline\'da '
        + 'bir gün önce ve o gün); hangi sayfada olursanız olun. Masa işini herkes görür ve tamamlayabilir; silmek ekleyenin ya da '
        + 'bir yöneticinin işidir. Kişisel işi yalnızca siz görürsünüz.'));
    this.list = h('div', { class: 'agenda-list', id: 'agenda-list' });
    this.host.appendChild(h('div', { class: 'panels agenda-page' }, form,
      h('section', { class: 'panel wide' }, h('header', null, h('h2', null, 'Ajanda')), this.list)));
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
    this.pastDays = res.past_days || this.pastDays;
    this.render();
  }

  render() {
    const now = new Date();
    const today = localDay(now);
    const time = hhmm(now);
    const late = this.items.filter((it) => isLate(it, today, time));
    const rest = this.items.filter((it) => !isLate(it, today, time));
    const box = clear(this.list);
    if (late.length) box.appendChild(this.group('Gecikmiş deadline\'lar', late, 'late', true));
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
    const done = h('input', { type: 'checkbox', title: it.done ? 'Tamamlandı – geri almak için tıklayın' : 'Tamamlandı olarak işaretle' });
    done.checked = it.done;
    done.addEventListener('change', () => this.mark(it, done.checked));
    const when = (withDay ? TR_DATE(it.day) + (it.time ? ' ' : '') : '') + (it.time || '');
    const what = h('td', { class: 'l what' }, h('span', { class: 'txt' }, it.text));
    if (it.deadline) what.appendChild(h('span', { class: 'desk-tag deadline' }, 'Deadline'));
    if (!it.shared) what.appendChild(h('span', { class: 'desk-tag' }, 'Kişisel'));
    const who = it.done ? '✓ ' + (it.done_by || '') + ' · ' + stampText(it.done_at) : it.by;
    const del = it.can_delete ? h('button', { class: 'iconbtn', type: 'button', title: 'Sil', onclick: () => this.remove(it) }, '✕') : null;
    return h('tr', { class: it.done ? 'done' : '', dataset: { id: String(it.id) } },
      h('td', { class: 'l chk' }, done), h('td', { class: 'l when' }, when || '–'), what,
      h('td', { class: 'l who muted', title: 'Ekleyen: ' + it.by + ' · ' + stampText(it.at) }, who), h('td', { class: 'act' }, del));
  }

  async submit() {
    if (this.adding) return;                         // one at a time: a double click adds the item once
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

  async mark(it, done) {
    try { this.take(await api.post('/api/agenda/' + it.id, { done })); } catch (err) { errorToast(err); this.render(); }
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
