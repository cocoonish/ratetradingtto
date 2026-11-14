// Kullanıcılar (administrators only): the requests waiting for approval, every account, and a new account.
import { api, session } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, modal } from '../ui.js';

const ROLE = { admin: 'Yönetici', user: 'Kullanıcı' };
const STATUS = { active: 'Etkin', pending: 'Onay bekliyor', disabled: 'Kapalı' };

function panel(title, note) {
  const body = h('div', { class: 'body' });
  const el = h('section', { class: 'panel wide' }, h('header', null, h('h2', { title }, title)), body);
  if (note) el.appendChild(h('div', { class: 'note' }, note));
  return { el, body };
}

function when(stamp) {
  if (!stamp) return '';
  const [d, t] = String(stamp).split(' ');
  const [y, m, day] = d.split('-');
  return day + '.' + m + '.' + y + (t ? ' ' + t.slice(0, 5) : '');
}

/** A password typed twice in a small dialog (the value never shows on the page). */
function askPassword(title) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({ title, width: 420, onClose: () => { if (!done) resolve(null); } });
    const a = h('input', { class: 'inp', type: 'password', autocomplete: 'new-password', style: { width: '100%' } });
    const b = h('input', { class: 'inp', type: 'password', autocomplete: 'new-password', style: { width: '100%' } });
    const err = h('div', { class: 'errtxt' });
    const finish = () => {
      if (a.value.length < 8) { err.textContent = 'Şifre en az 8 karakter olmalı'; a.focus(); return; }
      if (a.value !== b.value) { err.textContent = 'İki şifre aynı değil'; b.focus(); return; }
      done = true;
      m.close();
      resolve(a.value);
    };
    b.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(); });
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Yeni şifre'), a));
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Yeni şifre (tekrar)'), b));
    m.body.appendChild(err);
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: finish }, 'Kaydet'));
    a.focus();
  });
}

export class UsersPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.data = null;
  }

  async load() {
    clear(this.host);
    this.root = h('div', { class: 'panels users-page' });
    this.host.appendChild(this.root);
    await this.refresh();
  }

  async refresh() {
    const data = await api.get('/api/admin/users');
    if (this.dead) return;
    this.data = data;
    this.render();
  }

  async act(action, body, message) {
    try {
      const res = await api.post('/api/admin/users/' + action, body);
      if (res.demoted) {                          // one's own role given up: the dashboard opens again as a user
        toast('Yönetici yetkiniz kaldırıldı', 'ok', 4000);
        setTimeout(() => { window.location.hash = '#/masa'; window.location.reload(); }, 800);
        return;
      }
      this.data = res;
      if (!this.dead) this.render();
      if (message) toast(message, 'ok', 3200);
    } catch (err) { errorToast(err); }
  }

  render() {
    const d = this.data;
    if (this.ctx.setPending) this.ctx.setPending(d.pending);
    clear(this.root);
    const me = session.user;
    const btn = (label, cls, fn, title) => h('button', { class: 'btn sm' + (cls ? ' ' + cls : ''), type: 'button', title: title || '', onclick: fn }, label);

    // ---- requests
    const pending = d.accounts.filter((a) => a.status === 'pending');
    const req = panel('Onay bekleyen istekler (' + pending.length + ')',
      'Onaylanan kullanıcı isteğinde yazdığı isim ve şifreyle girer. "Mevcut kullanıcı": bu isim daha önce şifresiz (yalnız isimle) '
      + 'kullanılmış; onaylanınca o ismin kişisel girdileri ve senaryoları bu hesabın olur. Reddedilen yeni istek silinir, mevcut '
      + 'kullanıcının isteği reddedilince hesap eski hâline (şifresiz) döner.');
    if (!pending.length) {
      req.body.appendChild(h('div', { class: 'empty' }, 'Bekleyen istek yok.'));
    } else {
      const body = h('tbody');
      for (const a of pending) {
        const existing = !a.requested_new;
        body.appendChild(h('tr', null,
          h('td', { class: 'l' }, h('b', null, a.display)),
          h('td', null, when(a.requested_at)),
          h('td', { class: 'l' }, a.note || ''),
          h('td', { class: 'l' }, existing ? 'Mevcut kullanıcı · ' + a.inputs + ' girdi, ' + a.scenarios + ' senaryo' : 'Yeni'),
          h('td', null,
            btn('Onayla', 'primary', () => this.act('approve', { name: a.name }, a.display + ' onaylandı')),
            btn('Reddet', 'danger', async () => {
              if (!(await confirmDialog('İsteği reddet', a.display + ' adlı isteği reddedilsin mi?', 'Reddet', true))) return;
              this.act('reject', { name: a.name }, 'İstek reddedildi');
            }))));
      }
      req.body.appendChild(h('table', { class: 'plain' },
        h('thead', null, h('tr', null, h('th', { class: 'l' }, 'İsim'), h('th', null, 'İstek'), h('th', { class: 'l' }, 'Not'),
          h('th', { class: 'l' }, 'Kim'), h('th', null, ''))), body));
    }
    this.root.appendChild(req.el);

    // ---- every account
    const all = panel('Kullanıcılar (' + d.accounts.length + ')',
      'Yönetici bu sayfayı görür: istekleri onaylar, kullanıcı oluşturur, yönetici yetkisi verir ya da alır, şifre belirler, hesabı '
      + 'kapatır. Son yöneticinin yetkisi alınamaz, hesabı kapatılamaz. Kapatılan ya da şifresi değiştirilen kullanıcının açık '
      + 'oturumları sona erer. "Şifre yok": bu isim önceki sürümde yalnız isimle kullanılmış; kullanıcı aynı isimle hesap ister ya da '
      + 'burada şifre belirlersiniz.');
    const body = h('tbody');
    for (const a of d.accounts.filter((x) => x.status !== 'pending')) {
      const self = a.name === me;
      const tags = [h('span', { class: 'tag' + (a.role === 'admin' ? ' admin' : '') }, ROLE[a.role] || a.role)];
      if (a.status !== 'active') tags.push(' ', h('span', { class: 'tag off' }, STATUS[a.status] || a.status));
      if (!a.has_password) tags.push(' ', h('span', { class: 'tag' }, 'Şifre yok'));
      const acts = [];
      if (a.role === 'admin') {
        acts.push(btn('Yöneticiliği al', '', () => this.act('role', { name: a.name, admin: false }, a.display + ' artık kullanıcı')));
      } else {
        const make = btn('Yönetici yap', '', () => this.act('role', { name: a.name, admin: true }, a.display + ' artık yönetici'),
          a.has_password ? '' : 'Önce şifre belirleyin: şifresi olmayan hesap yönetici yapılamaz');
        make.disabled = !a.has_password;
        acts.push(make);
      }
      acts.push(btn(a.has_password ? 'Şifre sıfırla' : 'Şifre belirle', '', async () => {
        const pw = await askPassword(a.display + ' · yeni şifre');
        if (pw) this.act('password', { name: a.name, password: pw }, a.display + ' için şifre kaydedildi');
      }));
      if (a.status === 'disabled') {
        acts.push(btn('Aç', '', () => this.act('status', { name: a.name, active: true }, a.display + ' hesabı açıldı')));
      } else if (!self) {
        acts.push(btn('Kapat', 'danger', async () => {
          if (!(await confirmDialog('Hesabı kapat', a.display + ' artık giriş yapamaz; açık oturumları sona erer. Kişisel girdileri '
            + 've senaryoları silinmez, hesap yeniden açılabilir.', 'Kapat', true))) return;
          this.act('status', { name: a.name, active: false }, a.display + ' hesabı kapatıldı');
        }));
      }
      body.appendChild(h('tr', null,
        h('td', { class: 'l' }, h('b', null, a.display), self ? h('span', { class: 'muted' }, ' (siz)') : null),
        h('td', { class: 'l' }, ...tags),
        h('td', null, when(a.last_seen)),
        h('td', null, when(a.created_at)),
        h('td', null, String(a.inputs)),
        h('td', null, String(a.scenarios)),
        h('td', null, ...acts)));
    }
    all.body.appendChild(h('table', { class: 'plain' },
      h('thead', null, h('tr', null, h('th', { class: 'l' }, 'İsim'), h('th', { class: 'l' }, 'Rol · durum'), h('th', null, 'Son görülme'),
        h('th', null, 'Oluşturulma'), h('th', null, 'Kişisel girdi'), h('th', null, 'Senaryo'), h('th', null, ''))), body));
    this.root.appendChild(all.el);

    // ---- a new account
    const add = panel('Yeni kullanıcı', 'Oluşturulan hesap hemen etkindir; şifreyi kullanıcıya siz iletirsiniz, o da menüden '
      + '"Şifremi değiştir" ile değiştirebilir. Daha önce yalnız isimle kullanılmış bir isim yazılırsa o hesap bu şifreyi alır.');
    const name = h('input', { class: 'inp', type: 'text', maxlength: '40', placeholder: 'İsim' });
    const pw = h('input', { class: 'inp', type: 'password', maxlength: '200', placeholder: 'Şifre (en az 8 karakter)', autocomplete: 'new-password' });
    const admin = h('input', { type: 'checkbox' });
    const create = btn('Oluştur', 'primary', async () => {
      if (!name.value.trim()) { toast('İsim yazın', 'err'); name.focus(); return; }
      await this.act('create', { name: name.value, password: pw.value, admin: admin.checked }, name.value.trim() + ' oluşturuldu');
    });
    add.body.appendChild(h('div', { class: 'users-new' }, name, pw, h('label', null, admin, ' Yönetici'), create));
    this.root.appendChild(add.el);
  }

  destroy() {
    this.dead = true;
  }
}
