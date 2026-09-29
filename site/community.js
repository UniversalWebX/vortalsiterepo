/* vortal.space community: announcements and the launch chat.
   - a bar at the top of every page with the newest announcement (dismissible)
   - vortal.space/community, and the same panel on the Volatile page
   The chat opens when Volatile 1.0 does; reading needs no account, posting
   needs a Vortal account (the session account.js keeps in localStorage).
   Open pages poll /api/community/feed every few seconds while visible. */
(function () {
  'use strict';
  const KEY = 'vortal.session';
  const SEEN = 'vortal.announce.dismissed';
  const POLL_MS = 4000;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ls = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const session = () => { try { return JSON.parse(ls.get(KEY) || 'null'); } catch { return null; } };
  const safeLink = u => (/^https:\/\//i.test(u || '') || /^\/(?!\/)/.test(u || '') ? u : '');

  async function api(method, path, body) {
    const s = session();
    const headers = { 'Content-Type': 'application/json' };
    if (s && s.token) headers.Authorization = 'Bearer ' + s.token;
    try {
      const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
      const out = await r.json().catch(() => ({}));
      return { status: r.status, ...out };
    } catch {
      return { status: 0, message: "Couldn't reach vortal.space. Check your connection." };
    }
  }

  const time = ms => new Date(ms).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const day = ms => new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const launchText = ms => {
    const d = new Date(ms);
    const pacific = d.getTimezoneOffset() === 420;
    const local = d.toLocaleString(undefined, { weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    return pacific ? `${local} Pacific` : `${local} your time (5:30 PM Pacific)`;
  };

  /* ---------- the announcement bar on every page ---------- */
  async function banner() {
    const out = await api('GET', '/api/community/feed?lite=1');
    if (!out.ok || !out.announcements || !out.announcements.length) return;
    const a = out.announcements.slice().sort((x, y) => y.at - x.at)[0];
    if (Date.now() - a.at > 4 * 864e5) return;              // only fresh news
    if (ls.get(SEEN) === String(a.id)) return;
    const link = safeLink(a.link);
    const bar = document.createElement('aside');
    bar.className = 'vannounce';
    bar.setAttribute('aria-label', 'Announcement');
    bar.innerHTML = `
      <div class="wrap vannounce__inner">
        <span class="vannounce__tag">News</span>
        <p class="vannounce__text"><b>${esc(a.title)}</b>${a.body ? ` <span>${esc(a.body)}</span>` : ''}</p>
        ${link ? `<a class="vannounce__go" href="${esc(link)}">Open</a>` : ''}
        <a class="vannounce__go" href="/community">Chat</a>
        <button class="vannounce__x" type="button" aria-label="Dismiss">&times;</button>
      </div>`;
    bar.querySelector('.vannounce__x').addEventListener('click', () => { ls.set(SEEN, String(a.id)); bar.remove(); });
    const nav = document.querySelector('header.nav');
    if (nav) nav.parentNode.insertBefore(bar, nav); else document.body.prepend(bar);
  }

  /* ---------- the community panel ---------- */
  function panelHTML(heading) {
    return `
      <div class="vcom">
        ${heading ? `<header class="section-head section-head--tight"><h2>${heading}</h2><p class="section-head__meta"><a href="/community">Open the full chat</a></p></header>` : ''}
        <div class="vcom__grid">
          <section class="vcom__news" aria-label="Announcements">
            <h3 class="vcom__h">Announcements</h3>
            <div class="vcom__newslist" data-news><p class="vcom__dim">Loading…</p></div>
            <div data-announce></div>
          </section>
          <section class="vcom__chat" aria-label="Chat">
            <h3 class="vcom__h">Chat <span class="vcom__live" data-live hidden>live</span></h3>
            <ol class="vcom__log" data-log aria-live="polite"></ol>
            <div class="vcom__foot" data-foot></div>
          </section>
        </div>
      </div>`;
  }

  function mount(root, opts = {}) {
    root.innerHTML = panelHTML(opts.heading || '');
    const news = root.querySelector('[data-news]');
    const log = root.querySelector('[data-log]');
    const foot = root.querySelector('[data-foot]');
    const live = root.querySelector('[data-live]');
    const annBox = root.querySelector('[data-announce]');
    let last = 0;            // newest message id we have
    let since = 0;           // server time of the last poll (for deletions)
    let me = null;
    let open = false;
    let opensAt = 0;
    let footKey = '';
    let timer = 0;
    let busy = false;

    const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 40;

    function msgHTML(m) {
      const mod = me && me.role === 'mod';
      return `
        <li class="vcom__msg${m.role === 'mod' ? ' is-mod' : ''}" data-id="${m.id}">
          <span class="vcom__who">${esc(m.username)}${m.role === 'mod' ? ' <span class="vcom__badge">mod</span>' : ''}</span>
          <time class="vcom__time" datetime="${new Date(m.at).toISOString()}">${esc(time(m.at))}</time>
          <p class="vcom__body">${esc(m.body)}</p>
          ${mod ? `<span class="vcom__tools"><button type="button" data-del="${m.id}">Delete</button>${m.role !== 'mod' ? `<button type="button" data-mute="${esc(m.username)}">Mute</button>` : ''}</span>` : ''}
        </li>`;
    }

    function renderNews(list) {
      const mod = me && me.role === 'mod';
      news.innerHTML = list.length ? list.map(a => {
        const link = safeLink(a.link);
        return `
          <article class="vcom__ann${a.pinned ? ' is-pinned' : ''}">
            <p class="vcom__annmeta">${a.pinned ? '<span class="vcom__badge">pinned</span> ' : ''}${esc(day(a.at))} · ${esc(a.author)}</p>
            <h4 class="vcom__anntitle">${esc(a.title)}</h4>
            ${a.body ? `<p class="vcom__annbody">${esc(a.body)}</p>` : ''}
            ${link ? `<a class="vcom__annlink" href="${esc(link)}">Open <span aria-hidden="true">&rarr;</span></a>` : ''}
            ${mod ? `<button class="vcom__annx" type="button" data-unann="${a.id}">Remove</button>` : ''}
          </article>`;
      }).join('') : '<p class="vcom__dim">No announcements yet.</p>';
    }

    function renderFoot() {
      const s = session();
      const key = [open, !!s, me && me.role, me && !!me.mute, me && !!me.ban].join('|');
      if (key === footKey) return;
      footKey = key;
      if (!open && !(me && me.role === 'mod')) {
        foot.innerHTML = `
          <div class="vcom__locked">
            <p><b>The chat opens when Volatile 1.0 comes out:</b> ${esc(launchText(opensAt))}.</p>
            <p>${s ? `You're signed in as <b>${esc(s.username)}</b>, so you're all set.` : 'You\'ll need a free Vortal account to talk. <a href="/account?next=' + encodeURIComponent(location.pathname) + '">Make yours now</a> and claim your name.'}</p>
          </div>`;
        return;
      }
      if (!s) {
        foot.innerHTML = `<p class="vcom__dim"><a href="/account?next=${encodeURIComponent(location.pathname)}">Sign in or create a Vortal account</a> to chat.</p>`;
        return;
      }
      if (me && me.ban) { foot.innerHTML = '<p class="vcom__dim">This account is banned.</p>'; return; }
      if (me && me.mute) { foot.innerHTML = `<p class="vcom__dim">You're muted in the chat${me.mute.until ? ` until ${esc(new Date(me.mute.until).toLocaleString())}` : ''}.</p>`; return; }
      foot.innerHTML = `
        <form class="vcom__form" data-form>
          <label class="vcom__sr" for="vcom-in-${root.id || 'x'}">Message</label>
          <input id="vcom-in-${root.id || 'x'}" class="vcom__in" name="body" maxlength="300" autocomplete="off" placeholder="Say something as ${esc(s.username)}…" required>
          <button class="btn btn--solid vcom__send" type="submit">Send</button>
        </form>
        <p class="vcom__status" data-status role="alert" hidden></p>
        ${!open ? '<p class="vcom__dim">Moderator preview: the chat is closed to everyone else until launch.</p>' : ''}`;
      const form = foot.querySelector('[data-form]');
      const input = form.querySelector('input');
      const status = foot.querySelector('[data-status]');
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        form.querySelector('button').disabled = true;
        const out = await api('POST', '/api/community/chat', { body: text });
        form.querySelector('button').disabled = false;
        if (out.ok) {
          input.value = '';
          status.hidden = true;
          add([out.message], true);
          input.focus();
        } else {
          status.hidden = false;
          status.textContent = out.message || 'That didn\'t send.';
          if (out.status === 401) { footKey = ''; }
          if (out.error === 'muted' || out.error === 'banned') poll();
        }
      });
    }

    function renderAnnounceForm() {
      if (!(me && me.role === 'mod') || annBox.dataset.done) return;
      annBox.dataset.done = '1';
      annBox.innerHTML = `
        <details class="vcom__mod"><summary>Post an announcement</summary>
          <form class="cform" data-annform>
            <label class="cfield"><span>Title</span><input name="title" maxlength="120" required></label>
            <label class="cfield"><span>Text</span><textarea name="body" rows="3" maxlength="2000"></textarea></label>
            <label class="cfield"><span>Link (optional, e.g. /volatile)</span><input name="link" maxlength="300"></label>
            <label class="vcom__check"><input type="checkbox" name="pinned"> Pin it</label>
            <p class="cform__status" role="alert" hidden></p>
            <button class="btn btn--solid" type="submit">Post</button>
          </form>
        </details>`;
      const f = annBox.querySelector('[data-annform]');
      f.addEventListener('submit', async e => {
        e.preventDefault();
        const d = Object.fromEntries(new FormData(f));
        const out = await api('POST', '/api/community/announce', { title: d.title, body: d.body, link: d.link, pinned: !!d.pinned });
        const st = f.querySelector('.cform__status');
        st.hidden = false;
        st.textContent = out.ok ? 'Posted.' : (out.message || 'That didn\'t work.');
        if (out.ok) { f.reset(); poll(); }
      });
    }

    function add(list, mine) {
      if (!list.length) return;
      const stick = mine || atBottom();
      const fresh = list.filter(m => m.id > last && !log.querySelector(`[data-id="${m.id}"]`));
      if (!fresh.length) return;
      log.querySelector('.vcom__empty')?.remove();
      log.insertAdjacentHTML('beforeend', fresh.map(msgHTML).join(''));
      last = Math.max(last, ...fresh.map(m => m.id));
      while (log.children.length > 300) log.firstElementChild.remove();
      if (stick) log.scrollTop = log.scrollHeight;
    }

    async function poll() {
      if (busy) return;
      busy = true;
      const out = await api('GET', `/api/community/feed?after=${last}&since=${since}`);
      busy = false;
      if (!out.ok) {
        live.hidden = true;
        if (!log.children.length) log.innerHTML = `<li class="vcom__empty">${esc(out.message || 'Couldn\'t load the chat.')}</li>`;
        return;
      }
      const wasMod = me && me.role === 'mod';
      me = out.me || null;
      open = out.open;
      opensAt = out.opens_at;
      since = out.now;
      live.hidden = !open;
      if ((me && me.role === 'mod') !== wasMod) log.innerHTML = '';   // redraw with the tools
      if ((me && me.role === 'mod') !== wasMod) last = 0;
      renderNews(out.announcements || []);
      renderAnnounceForm();
      (out.deleted || []).forEach(id => log.querySelector(`[data-id="${id}"]`)?.remove());
      add(out.messages || []);
      if (!log.children.length) {
        log.innerHTML = `<li class="vcom__empty">${open || (me && me.role === 'mod') ? 'No messages yet. Say hi!' : 'Messages will show up here once the chat opens.'}</li>`;
      }
      renderFoot();
    }

    // moderator tools on messages and announcements
    root.addEventListener('click', async e => {
      const del = e.target.closest('[data-del]');
      const mute = e.target.closest('[data-mute]');
      const un = e.target.closest('[data-unann]');
      if (del) {
        const out = await api('POST', '/api/community/delete', { id: +del.dataset.del });
        if (out.ok) log.querySelector(`[data-id="${del.dataset.del}"]`)?.remove();
      } else if (mute) {
        const mins = prompt(`Mute ${mute.dataset.mute} for how many minutes? (blank = until unmuted, 0 = unmute)`, '60');
        if (mins === null) return;
        const reason = mins.trim() === '0' ? '' : (prompt('Reason (optional)', '') || '');
        const out = await api('POST', '/api/community/mute', { username: mute.dataset.mute, minutes: mins.trim() === '' ? -1 : Number(mins), reason });
        alert(out.ok ? (out.muted ? `${out.username} is muted.` : `${out.username} is unmuted.`) : (out.message || 'That didn\'t work.'));
      } else if (un) {
        if (!confirm('Remove this announcement?')) return;
        const out = await api('POST', '/api/community/unannounce', { id: +un.dataset.unann });
        if (out.ok) poll();
      }
    });

    // every few seconds while the page is in front; every 30 s in a background tab
    let polls = 0;
    let lastPoll = 0;
    const loop = () => {
      clearTimeout(timer);
      if (!root.isConnected) return;
      const visible = document.visibilityState === 'visible';
      if (visible || polls === 0 || Date.now() - lastPoll > 30000) {
        polls++;
        lastPoll = Date.now();
        poll();
      }
      timer = setTimeout(loop, POLL_MS);
    };
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') loop(); });
    loop();
  }

  function page(el) {
    el.innerHTML = `
      <section class="contact vcom-page">
        <div class="wrap">
          <nav class="crumbs" aria-label="Breadcrumb"><a href="/">Vortal</a><span aria-hidden="true">/</span><span aria-current="page">Community</span></nav>
          <h1 class="product__name">Community</h1>
          <p class="product__lede">News from Vortal, and a live chat for everyone playing <a href="/volatile">Volatile</a>. Be kind: moderators can delete messages and mute accounts.</p>
          <div id="vcom-main"></div>
        </div>
      </section>`;
    mount(el.querySelector('#vcom-main'));
  }

  window.VortalCommunity = { mount, page, banner };
  banner();
})();
