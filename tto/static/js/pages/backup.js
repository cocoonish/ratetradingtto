// Yedekleme (administrators only): when the database's daily backup is taken and where it goes - the time, the
// backup folder and its second copy (another drive, a share of the office network) -, where each setting comes from,
// a backup now, and the newest backups of each folder.  What is saved here comes before the command line and the
// defaults and applies without a restart.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog } from '../ui.js';
import { num, isoToTr } from '../format.js';

const SOURCE = { saved: 'yönetici seçimi (bu sayfa)', cli: 'komut satırı / ortam değişkeni', default: 'varsayılan' };
const FIELDS = [
  { key: 'time', label: 'Yedek saati', id: 'bk-time', cls: 'inp time', placeholder: 'SS:DD', help: (d) => 'Her gün bu saatte (varsayılan '
    + (d.default_time || '17:30') + '). O saatte dashboard kapalıysa kaçırılan yedek açıldıktan sonra alınır.' },
  { key: 'dir', label: 'Yedek klasörü', id: 'bk-dir', cls: 'inp', placeholder: 'E:\\tto-yedek', help: () => 'Tam yol: bu bilgisayarın '
    + 'bir sürücüsü (C:\\…), eşlenmiş bir sürücü ya da ofis ağındaki bir paylaşım (\\\\sunucu\\paylaşım\\…). Yoksa açılır.' },
  { key: 'copy_dir', label: 'İkinci kopya klasörü', id: 'bk-copy', cls: 'inp', placeholder: 'boş = ikinci kopya yok', help: () => 'Başka bir '
    + 'sürücü ya da ağ paylaşımı: disk bozulursa yedek orada kalır. Boş = ikinci kopya yok.' },
];

/** "2026-11-15 17:30:02" -> "15.11.2026 17:30" */
function when(stamp) {
  if (!stamp) return '';
  const [d, t] = String(stamp).split(' ');
  return isoToTr(d) + (t ? ' ' + t.slice(0, 5) : '');
}

const mb = (bytes) => num((bytes || 0) / 1048576, 1) + ' MB';
const folderOf = (path) => String(path || '').replace(/[\\/][^\\/]*$/, '');

export class BackupPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.data = null;
    this.dirty = false;                    // the form holds what was typed: a refresh leaves it alone
    this.loadedAt = 0;
    this.inputs = {};
    this.errs = {};
    this.helps = {};
  }

  async load() {
    clear(this.host);
    this.root = h('div', { class: 'panels backup-page' });
    this.host.appendChild(this.root);
    this.build();
    await this.fetch();
  }

  /** A new generation comes every few seconds; the folders change once a day: asked again at most every 30 s. */
  async refresh() {
    if (Date.now() - this.loadedAt < 30000) return;
    await this.fetch();
  }

  async fetch() {
    const d = await api.get('/api/admin/backup');
    if (!this.dead) this.show(d);
  }

  build() {
    const panel = (id, title) => {
      const body = h('div', { class: 'body' });
      const el = h('section', { class: 'panel wide', id }, h('header', null, h('h2', null, title)), body);
      this.root.appendChild(el);
      return el;
    };
    // ---- the settings
    const set = panel('bk-settings', 'Günlük yedek · saat ve klasörler');
    const form = h('div', { class: 'bk-form' });
    for (const f of FIELDS) {
      const inp = h('input', { class: f.cls, id: f.id, placeholder: f.placeholder, spellcheck: 'false', autocomplete: 'off',
        maxlength: f.key === 'time' ? '5' : '400' });
      inp.addEventListener('input', () => { this.dirty = true; inp.classList.remove('bad'); this.errs[f.key].textContent = ''; });
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.save(); });
      this.inputs[f.key] = inp;
      this.errs[f.key] = h('div', { class: 'errtxt', id: f.id + '-err' });
      this.helps[f.key] = h('div', { class: 'help' });
      form.appendChild(h('label', { for: f.id }, f.label));
      form.appendChild(h('div', { class: 'cell' }, inp, this.errs[f.key]));
      form.appendChild(this.helps[f.key]);
    }
    this.copyHint = h('div', { class: 'bk-hint hidden', id: 'bk-copy-hint' });
    form.appendChild(h('span'));
    form.appendChild(this.copyHint);
    form.appendChild(h('span'));
    set.querySelector('.body').appendChild(form);
    this.saveBtn = h('button', { class: 'btn primary', type: 'button', id: 'bk-save' }, 'Kaydet');
    this.saveBtn.addEventListener('click', () => this.save());
    this.resetBtn = h('button', { class: 'btn', type: 'button', id: 'bk-reset', title: 'Kaydedilen seçimi sil: komut satırının / varsayılanların saati ve klasörleri' },
      'Varsayılanlara dön');
    this.resetBtn.addEventListener('click', () => this.reset());
    this.savedInfo = h('span', { class: 'muted', id: 'bk-saved' });
    set.querySelector('.body').appendChild(h('div', { class: 'bk-actions' }, this.saveBtn, this.resetBtn, this.savedInfo));
    this.sources = h('div', { class: 'bk-sources' });
    set.querySelector('.body').appendChild(this.sources);
    set.appendChild(h('div', { class: 'note' }, 'Burada kaydedilen seçim komut satırının ve ortam değişkenlerinin, onlar da varsayılanların önündedir; '
      + 'yeniden başlatma gerekmez, en geç 15 saniye içinde geçerli olur. Klasör değişince eski yedekler taşınmaz, eski klasörde kalır '
      + '(geri dönüş komutu her klasöre bakar); her klasörde en yeni 30 yedek tutulur. Yeni yedek klasöründe henüz yedek yoksa ilk yedek '
      + 'hemen alınır. Bulut eşitleme klasörleri (OneDrive, Dropbox, Google Drive, iCloud Drive, Box) kabul edilmez: veritabanında '
      + 'Bloomberg verisi ve şifre özetleri var; masanın kuralı gereği bunlar hiçbir dış hizmete gitmez.'));
    // ---- a backup now
    const now = panel('bk-now-panel', 'Şimdi yedek al');
    this.nowBtn = h('button', { class: 'btn primary', type: 'button', id: 'bk-now', title: 'Şu anki ayarlarla bir yedek al: dosya, boyutu, ikinci kopya' },
      'Şimdi yedek al');
    this.nowBtn.addEventListener('click', () => this.backupNow());
    this.result = h('div', { class: 'bk-result', id: 'bk-result' });
    this.state = h('div', { class: 'bk-state', id: 'bk-state' });
    now.querySelector('.body').appendChild(h('div', { class: 'bk-actions' }, this.nowBtn,
      h('span', { class: 'muted' }, 'Bugünün dosyası aynı adla yenilenir; yedek saatinden önce alınırsa o saatteki yedek de alınır.')));
    now.querySelector('.body').appendChild(this.result);
    now.querySelector('.body').appendChild(this.state);
    // ---- the newest backups of each folder
    this.lists = panel('bk-lists', 'Son yedekler').querySelector('.body');
  }

  show(d) {
    this.data = d;
    this.loadedAt = Date.now();
    if (!this.dirty) {
      this.inputs.time.value = d.time || '';
      this.inputs.dir.value = d.dir || '';
      this.inputs.copy_dir.value = d.copy_dir || '';
    }
    for (const f of FIELDS) this.helps[f.key].textContent = f.help(d);
    // no second copy: said, with a hint to choose one
    this.copyHint.classList.toggle('hidden', !!d.copy_dir);
    this.copyHint.textContent = d.copy_dir ? '' : 'İkinci kopya seçilmedi: yedekler yalnızca yedek klasöründe - o disk bozulursa hepsi '
      + 'gider. Başka bir sürücüde ya da ofis ağındaki bir paylaşımda bir klasör seçin (ör. E:\\tto-yedek, \\\\sunucu\\paylaşım\\tto-yedek).'
      + (d.d_drive === false ? ' Bu bilgisayarda D: sürücüsü yok: varsayılan D:\\tto-yedek kullanılamıyor.' : '');
    this.savedInfo.textContent = d.saved ? 'Kaydeden: ' + this.ctx.displayName(d.saved.by) + ' · ' + when(d.saved.at)
      : 'Kayıtlı seçim yok: komut satırı / varsayılanlar geçerli.';
    this.resetBtn.disabled = !d.saved;
    this.renderSources(d);
    this.renderState(d);
    this.renderLists(d);
  }

  /** What applies now, where it comes from, and what would apply without the choice saved here. */
  renderSources(d) {
    const shown = (k, v) => (v ? v : (k === 'copy_dir' ? '— yok' : '—'));
    const t = h('table', { class: 'plain', id: 'bk-sources' }, h('tr', null, h('th', { class: 'l' }, 'Ayar'), h('th', { class: 'l' }, 'Geçerli'),
      h('th', { class: 'l' }, 'Nereden'), h('th', { class: 'l' }, 'Seçim olmasa (komut satırı / varsayılan)')));
    for (const f of FIELDS) {
      t.appendChild(h('tr', { 'data-key': f.key }, h('td', { class: 'l' }, f.label), h('td', { class: 'l mono' }, shown(f.key, d[f.key])),
        h('td', { class: 'l' }, SOURCE[d.source[f.key]] || d.source[f.key]), h('td', { class: 'l mono muted' }, shown(f.key, d.base[f.key]))));
    }
    clear(this.sources).appendChild(t);
  }

  /** The last failures: of the backup (tried again after half an hour), of its second copy (two days: the alarm) - and a
   * day's backup that went to the dashboard's own folder because the chosen one could not be written: whether it has
   * reached the chosen folder since. */
  renderState(d) {
    const box = clear(this.state);
    const fb = d.fallback;
    if (fb) {
      const day = fb.today ? 'Bugünkü yedek' : isoToTr(fb.day) + ' yedeği';
      const waiting = (fb.waiting || []).length;
      if (waiting) {
        box.appendChild(h('div', { class: 'errtxt', id: 'bk-fallback' }, (waiting > 1 ? waiting + ' günün yedeği' : day)
          + ' seçilen klasöre yazılamadı (' + when(fb.at) + ') – dashboard\'un kendi klasörüne alındı: ', h('span', { class: 'mono' }, fb.dir),
          '. Seçilen klasöre henüz ulaşmadı: yarım saatte bir yeniden denenir'
          + (fb.error ? ' (son deneme ' + when(fb.error.at) + ': ' + fb.error.text + ')' : '') + '; ulaşınca veritabanı alarmı kapanır.'));
      } else {
        box.appendChild(h('div', { class: 'bk-hint', id: 'bk-fallback' }, day + ' seçilen klasöre yazılamadığı için önce dashboard\'un kendi '
          + 'klasörüne alındı (' + when(fb.at) + '); ' + when(fb.reached_at) + ' itibarıyla seçilen klasörde de.'));
      }
    }
    if (d.error) {
      box.appendChild(h('div', { class: 'errtxt' }, 'Son yedek denemesi başarısız (' + when(d.error.at) + '): ' + d.error.text
        + ' – yarım saat sonra yeniden denenir.'));
    }
    if (d.copy_error) {
      box.appendChild(h('div', { class: d.copy_failed > 1 ? 'errtxt' : 'bk-hint' }, 'İkinci kopya ' + (d.copy_failed > 1 ? d.copy_failed + ' gündür' : 'son yedekte')
        + ' alınamadı (' + when(d.copy_error.at) + '): ' + d.copy_error.text + (d.copy_failed > 1 ? ' – veritabanı alarmı çalar.' : '')));
    }
  }

  renderLists(d) {
    const box = clear(this.lists);
    const block = (title, folder, items, count, id, empty) => {
      box.appendChild(h('div', { class: 'bk-sub' }, title + ' · ', h('span', { class: 'mono' }, folder), ' · ' + count + ' / ' + d.keep));
      if (!items.length) { box.appendChild(h('div', { class: 'empty' }, empty)); return; }
      const t = h('table', { class: 'plain', id }, h('tr', null, h('th', { class: 'l' }, 'Dosya'), h('th', { class: 'l' }, 'Alındı'), h('th', null, 'Boyut')));
      for (const b of items) t.appendChild(h('tr', null, h('td', { class: 'l mono' }, b.name), h('td', { class: 'l' }, when(b.at)), h('td', null, mb(b.bytes))));
      box.appendChild(t);
    };
    block('Yedek klasörü', d.dir, d.backups, d.count, 'bk-list', 'Bu klasörde henüz yedek yok.');
    if (d.copy_dir) {
      block('İkinci kopya', d.copy_dir, d.copies, d.copy_count, 'bk-copies', 'Bu klasörde henüz kopya yok: bir sonraki yedekle (ya da "Şimdi yedek al" ile) yazılır.');
    } else {
      box.appendChild(h('div', { class: 'bk-sub' }, 'İkinci kopya · seçilmedi'));
    }
    // (where the day's backup went while the chosen folder could not be written)
    if (d.own) block('Dashboard\'un kendi klasörü', d.own.dir, d.own.backups, d.own.count, 'bk-own', 'Bu klasörde yedek yok.');
  }

  showErrors(errors) {
    for (const f of FIELDS) {
      const text = (errors && errors[f.key]) || '';
      this.errs[f.key].textContent = text;
      this.inputs[f.key].classList.toggle('bad', !!text);
    }
  }

  async save() {
    const values = { time: this.inputs.time.value, dir: this.inputs.dir.value, copy_dir: this.inputs.copy_dir.value };
    this.showErrors({});
    this.saveBtn.disabled = true;
    try {
      const d = await api.post('/api/admin/backup', { values });
      this.dirty = false;
      if (!this.dead) this.show(d);
      toast('Yedek ayarları kaydedildi: yeniden başlatmadan geçerli', 'ok');
      this.ctx.refreshNow();                 // (the status window says the folders too)
    } catch (err) {
      if (err.data && err.data.errors) this.showErrors(err.data.errors);
      else errorToast(err);
    } finally {
      this.saveBtn.disabled = false;
    }
  }

  async reset() {
    if (!(await confirmDialog('Varsayılanlara dön', 'Burada kaydedilen seçim silinsin mi? Komut satırının / varsayılanların saati ve klasörleri '
      + 'geçerli olur; alınmış yedekler taşınmaz.', 'Varsayılanlara dön'))) return;
    try {
      const d = await api.post('/api/admin/backup', { reset: true });
      this.dirty = false;
      this.showErrors({});
      if (!this.dead) this.show(d);
      toast('Komut satırı / varsayılan ayarlar geçerli', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  async backupNow() {
    this.nowBtn.disabled = true;
    clear(this.result).appendChild(h('span', { class: 'muted' }, 'Yedek alınıyor…'));
    try {
      const d = await api.post('/api/admin/backup/now');
      if (this.dead) return;
      this.show(d);
      this.renderResult(d.result);
      if (d.result.fallback) toast('Seçilen klasöre yazılamadı: yedek dashboard\'un kendi klasörüne alındı', 'err', 6000);
      else toast('Yedek alındı', 'ok');
      this.ctx.refreshNow();
    } catch (err) {
      clear(this.result).appendChild(h('div', { class: 'errtxt' }, err.message));
      this.fetch().catch(() => {});
    } finally {
      this.nowBtn.disabled = false;
    }
  }

  /** The backup just taken: its file and size - in the dashboard's own folder when the chosen one could not be
   * written -, and whether its second copy was written. */
  renderResult(r) {
    const box = clear(this.result);
    const name = String(r.path || '').split(/[\\/]/).pop();
    if (r.fallback) {
      box.appendChild(h('div', { class: 'errtxt' }, '⚠ Seçilen yedek klasörüne yazılamadı (' + r.fallback.error.text + ') – yedek dashboard\'un '
        + 'kendi klasörüne alındı; seçilen klasör yarım saatte bir yeniden denenir, yazılabilince dosya oraya kopyalanır.'));
    }
    box.appendChild(h('div', { class: 'bk-ok' }, '✓ Yedek alındı: ', h('b', { class: 'mono' }, name), ' · ' + mb(r.bytes) + ' · '
      + num(r.seconds, 1) + ' sn · ', h('span', { class: 'mono' }, folderOf(r.path))));
    const c = r.copy;
    if (!c) box.appendChild(h('div', { class: 'muted' }, 'İkinci kopya: yok (ikinci kopya klasörü seçilmedi)'));
    else if (c.error) box.appendChild(h('div', { class: 'errtxt' }, 'İkinci kopya: YAZILAMADI – ' + c.error.text));
    else box.appendChild(h('div', { class: 'bk-ok' }, '✓ İkinci kopya yazıldı: ', h('span', { class: 'mono' }, c.path)));
    if (r.removed && r.removed.length) {
      box.appendChild(h('div', { class: 'muted' }, 'Eski yedekler silindi (en yeni ' + (this.data ? this.data.keep : 30) + ' kalır): ' + r.removed.join(', ')));
    }
  }

  destroy() {
    this.dead = true;
  }
}
