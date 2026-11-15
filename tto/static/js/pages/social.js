// Sosyal: the desk's chat.  Everybody signed in writes; a message shows up on every open page at once (the live
// stream says the chat changed, the page asks for what it has, again).  Messages are kept; the latest come first,
// earlier ones on request.  One takes back one's own message.  What is written goes on the page as text only.
import { api } from '../api.js';
import { h, clear, errorToast, confirmDialog } from '../ui.js';
import { markChatSeen, dayTitle, localDay, shiftDay } from '../desk.js';

const LONGEST = 1000;
/** messages of one person within this many minutes go under one name */
const GROUP_MINUTES = 5;

const minutesOf = (stamp) => {
  const [d, t] = stamp.split(' ');
  return Date.parse(d + 'T' + t) / 60000;
};

function dayLabel(iso) {
  const today = localDay(new Date());
  if (iso === today) return 'Bugün · ' + dayTitle(iso);
  if (iso === shiftDay(today, -1)) return 'Dün · ' + dayTitle(iso);
  return dayTitle(iso);
}

export class SocialPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.msgs = [];
    this.more = false;
    this.reading = false;
    this.again = false;
    this.onVisible = () => { if (document.visibilityState === 'visible') this.markSeen(); };
  }

  async load() {
    clear(this.host);
    this.log = h('div', { class: 'chatlog', id: 'chat-log', role: 'log', 'aria-live': 'polite' });
    this.newer = h('button', { class: 'chat-newer hidden', type: 'button', id: 'chat-newer' }, 'Yeni mesaj ↓');
    this.newer.addEventListener('click', () => this.toBottom());
    this.log.addEventListener('scroll', () => {
      if (!this.atBottom()) return;
      this.newer.classList.add('hidden');
      this.markSeen();                                 // scrolled down to the last message: read
    });
    this.text = h('textarea', { class: 'inp', id: 'chat-text', rows: '1', maxlength: String(LONGEST),
      placeholder: 'Mesaj yazın…   Enter gönderir · Shift+Enter alt satır' });
    this.send = h('button', { class: 'btn primary', type: 'button', id: 'chat-send' }, 'Gönder');
    this.count = h('span', { class: 'muted chat-count' });
    this.text.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.submit(); }
    });
    this.text.addEventListener('input', () => this.typed());
    this.send.addEventListener('click', () => this.submit());
    const panel = h('section', { class: 'panel wide social' },
      h('header', null, h('h2', null, 'Masa sohbeti'),
        h('span', { class: 'muted' }, 'Giriş yapmış herkes görür · mesajlar saklanır · kendi mesajınızı silebilirsiniz')),
      h('div', { class: 'chatwrap' }, this.log, this.newer),
      h('div', { class: 'chatin' }, this.text, h('div', { class: 'chatside' }, this.send, this.count)));
    this.host.appendChild(h('div', { class: 'panels' }, panel));
    const res = await api.get('/api/social');
    if (this.dead) return;
    this.msgs = res.messages;
    this.more = res.more;
    this.render('bottom');
    document.addEventListener('visibilitychange', this.onVisible);
    this.text.focus();
  }

  /** The market's generations do not concern the chat (its own news come through ``onDesk``). */
  refresh() { return Promise.resolve(); }

  onDesk(changed) {
    if (changed.includes('chat')) this.reload();
  }

  /** Read again what the page has (and what came after it): new messages, and the ones taken back. */
  async reload() {
    if (this.reading) { this.again = true; return; }
    this.reading = true;
    try {
      do {
        this.again = false;
        const first = this.msgs.length ? this.msgs[0].id : null;
        const res = await api.get('/api/social', first === null ? {} : { since: first });
        if (this.dead) return;
        const had = new Set(this.msgs.map((m) => m.id));
        this.msgs = res.messages;
        this.more = res.more;
        this.render(this.msgs.some((m) => !had.has(m.id)) ? 'new' : 'stay');
      } while (this.again);
    } catch (err) {
      if (!err.network && err.status !== 401) errorToast(err);
    } finally {
      this.reading = false;
    }
  }

  async older() {
    if (!this.msgs.length) return;
    try {
      const res = await api.get('/api/social', { before: this.msgs[0].id });
      if (this.dead) return;
      const had = new Set(this.msgs.map((m) => m.id));
      this.msgs = res.messages.filter((m) => !had.has(m.id)).concat(this.msgs);
      this.more = res.more;
      this.render('older');
    } catch (err) { errorToast(err); }
  }

  atBottom() {
    return this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight < 48;
  }

  toBottom() {
    this.log.scrollTop = this.log.scrollHeight;
    this.newer.classList.add('hidden');
    this.markSeen();
  }

  markSeen() {
    if (this.dead || document.visibilityState !== 'visible' || !this.msgs.length) return;
    if (this.atBottom()) markChatSeen(this.msgs[this.msgs.length - 1].id);
  }

  /** ``how``: 'bottom' (to the last message), 'new' (follow new messages when at the bottom, else say they came),
   * 'older' (earlier messages above: the view stays where it was), 'stay'. */
  render(how) {
    const log = this.log;
    const follow = how === 'bottom' || (how === 'new' && this.atBottom());
    const fromBottom = log.scrollHeight - log.scrollTop;
    clear(log);
    if (this.more) {
      log.appendChild(h('div', { class: 'chat-more' },
        h('button', { class: 'btn sm', type: 'button', id: 'chat-older', onclick: () => this.older() }, 'Daha eski mesajlar')));
    }
    if (!this.msgs.length) log.appendChild(h('div', { class: 'empty' }, 'Henüz mesaj yok – ilk mesajı siz yazın.'));
    let day = null;
    let prev = null;
    for (const m of this.msgs) {
      const d = m.at.slice(0, 10);
      if (d !== day) {
        log.appendChild(h('div', { class: 'chatday' }, h('span', null, dayLabel(d))));
        day = d;
        prev = null;
      }
      const joined = !!prev && prev.user === m.user && minutesOf(m.at) - minutesOf(prev.at) < GROUP_MINUTES;
      log.appendChild(this.message(m, joined));
      prev = m;
    }
    if (follow) this.toBottom();
    else if (how === 'older') log.scrollTop = log.scrollHeight - fromBottom;
    else if (how === 'new') this.newer.classList.remove('hidden');
  }

  message(m, joined) {
    const time = m.at.slice(11, 16);
    const row = h('div', { class: 'msg' + (m.mine ? ' mine' : '') + (joined ? ' joined' : ''), dataset: { id: String(m.id) } },
      h('span', { class: 'av', 'aria-hidden': 'true' }, joined ? '' : (m.name.trim()[0] || '?').toLocaleUpperCase('tr')));
    const body = h('div', { class: 'mb' });
    if (!joined) body.appendChild(h('div', { class: 'mh' }, h('b', { class: 'who' }, m.name), h('time', { title: m.at }, time)));
    body.appendChild(h('div', { class: 'mt', title: joined ? time : null }, m.text));
    row.appendChild(body);
    if (m.mine) {
      row.appendChild(h('button', { class: 'iconbtn del', type: 'button', title: 'Mesajı sil (herkesten)',
        onclick: () => this.remove(m) }, '✕'));
    }
    return row;
  }

  typed() {
    const t = this.text;
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight + 2, 160) + 'px';
    const n = t.value.length;
    this.count.textContent = n > LONGEST * 0.8 ? n + ' / ' + LONGEST : '';
  }

  async submit() {
    const text = this.text.value;
    if (!text.trim() || this.sending) return;
    // the box empties at once (the next message can be typed while this one goes); not sent: it comes back
    this.sending = true;
    this.text.value = '';
    this.typed();
    try {
      const m = await api.post('/api/social', { text });
      if (this.dead) return;
      if (!this.msgs.some((x) => x.id === m.id)) this.msgs.push(m);
      this.render('bottom');
    } catch (err) {
      errorToast(err);
      if (!this.dead && !this.text.value) { this.text.value = text; this.typed(); }
    } finally {
      this.sending = false;
    }
  }

  async remove(m) {
    if (!(await confirmDialog('Mesajı sil', 'Bu mesaj herkesten silinsin mi?', 'Sil', true))) return;
    try {
      await api.del('/api/social/' + m.id);
      if (this.dead) return;
      this.msgs = this.msgs.filter((x) => x.id !== m.id);
      this.render('stay');
    } catch (err) { errorToast(err); }
  }

  destroy() {
    this.dead = true;
    document.removeEventListener('visibilitychange', this.onVisible);
  }
}
