/* vortal.space/account — Vortal accounts (Volatile uses them for online play).
   Sign in / create an account, change password, sign out, delete; moderators
   also get the ban list, ban / unban and the moderation log.
   The session token lives in this browser's localStorage and goes to /api/*
   as "Authorization: Bearer …". */
(function () {
  'use strict';
  const KEY = 'vortal.session';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; } },
    set(v) { try { v ? localStorage.setItem(KEY, JSON.stringify(v)) : localStorage.removeItem(KEY); } catch { /* private mode */ } },
  };

  async function api(method, path, body) {
    const s = store.get();
    const headers = { 'Content-Type': 'application/json' };
    if (s && s.token) headers.Authorization = 'Bearer ' + s.token;
    try {
      const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
      const out = await r.json().catch(() => ({}));
      return { status: r.status, ...out };
    } catch {
      return { status: 0, message: "Couldn't reach vortal.space. Check your connection." };
    }
  }

  const when = ms => ms ? new Date(ms).toLocaleString() : '';

  function shell(inner) {
    return `
      <section class="contact acct">
        <div class="wrap contact__grid">
          <div class="contact__intro">
            <nav class="crumbs" aria-label="Breadcrumb"><a href="/">Vortal</a><span aria-hidden="true">/</span><span aria-current="page">Account</span></nav>
            <h1 class="product__name">Your Vortal account</h1>
            ${window.Vortal && !window.Vortal.released() ? `
            <p class="product__lede">One account for Vortal's games. From <a href="/volatile">Volatile 1.0</a> (October 1) it's your name in co-op: nobody else can use it, it keeps your items between devices, and it's needed to host or join online games. Solo play won't need one.</p>
            <p class="product__lede">Make yours now to claim your name before launch. Once 1.0 is out, sign in once from the game's main menu → Account and it remembers you.</p>` : `
            <p class="product__lede">One account for Vortal's games. In <a href="/volatile">Volatile</a> it's your name in co-op: nobody else can use it, it keeps your items between devices, and it's needed to host or join online games. Solo play doesn't need one.</p>
            <p class="product__lede">The game remembers you after you sign in once. Sign in there from the main menu → Account.</p>`}
          </div>
          <div class="contact__card" id="acct-card">${inner}</div>
        </div>
      </section>`;
  }

  function signInHTML(note) {
    return `
      <form class="cform" id="acct-form" novalidate>
        ${note ? `<p class="acct__note">${esc(note)}</p>` : ''}
        <label class="cfield"><span>Username</span>
          <input name="username" autocomplete="username" maxlength="20" required pattern="[A-Za-z0-9_]{3,20}"></label>
        <label class="cfield"><span>Password</span>
          <input name="password" type="password" autocomplete="current-password" minlength="8" maxlength="200" required></label>
        <label class="cfield" id="acct-claim" hidden><span>Claim key (reserved names only)</span>
          <input name="claim_key" type="password" autocomplete="off"></label>
        <p class="cform__status" id="acct-status" role="alert" hidden></p>
        <div class="acct__row">
          <button class="btn btn--solid" type="submit" data-act="login">Sign in</button>
          <button class="btn btn--line" type="submit" data-act="register">Create account</button>
        </div>
        <p class="acct__small">Usernames are 3–20 letters, numbers or underscores. Passwords need at least 8 characters.</p>
      </form>`;
  }

  function signedInHTML(me) {
    const mod = me.role === 'mod';
    const ban = me.ban ? `<p class="acct__ban">This account is banned from online play${me.ban.until ? ` until ${esc(when(me.ban.until))}` : ''}${me.ban.reason ? `: ${esc(me.ban.reason)}` : '.'}</p>` : '';
    return `
      <div class="acct__me">
        <p class="acct__hello">Signed in as <strong>${esc(me.username)}</strong>${mod ? ' <span class="tag acct__mod">Moderator</span>' : ''}</p>
        <p class="acct__small">Account since ${esc(new Date(me.created_at).toLocaleDateString())}</p>
        ${ban}
        <div class="acct__row"><button class="btn btn--line" type="button" id="acct-out">Sign out</button></div>
      </div>
      <details class="acct__box"><summary>Change password</summary>
        <form class="cform" id="acct-pw" novalidate>
          <label class="cfield"><span>Current password</span><input name="old" type="password" autocomplete="current-password" required></label>
          <label class="cfield"><span>New password</span><input name="new" type="password" autocomplete="new-password" minlength="8" required></label>
          <p class="cform__status" role="alert" hidden></p>
          <button class="btn btn--solid" type="submit">Change password</button>
          <p class="acct__small">Changing it signs you out everywhere else, including the game on other devices.</p>
        </form></details>
      <details class="acct__box"><summary>Delete account</summary>
        <form class="cform" id="acct-del" novalidate>
          <p class="acct__small">This deletes your account for good. Your worlds and saves in the game are not affected, but you'll need a new account to play online.</p>
          <label class="cfield"><span>Password</span><input name="password" type="password" autocomplete="current-password" required></label>
          <p class="cform__status" role="alert" hidden></p>
          <button class="btn btn--line acct__danger" type="submit">Delete my account</button>
        </form></details>
      ${mod ? `<div class="acct__mods" id="acct-mods"><h2>Moderation</h2><p class="acct__small">Loading…</p></div>` : ''}`;
  }

  function status(form, text, good) {
    const p = form.querySelector('.cform__status');
    if (!p) return;
    p.hidden = !text;
    p.textContent = text || '';
    p.classList.toggle('is-good', !!good);
  }

  async function render(page, note) {
    page.innerHTML = shell('<p class="acct__small">Loading…</p>');
    const card = page.querySelector('#acct-card');
    const s = store.get();
    if (s && s.token) {
      const me = await api('GET', '/api/account/me');
      if (me.ok) return showMe(page, card, me);
      if (me.status === 401) store.set(null);
      else { card.innerHTML = `<p class="acct__small">${esc(me.message || 'Something went wrong.')}</p>`; return; }
    }
    card.innerHTML = signInHTML(note);
    const form = card.querySelector('#acct-form');
    let act = 'login';
    form.querySelectorAll('button[type=submit]').forEach(b => b.addEventListener('click', () => { act = b.dataset.act; }));
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      if (!data.claim_key) delete data.claim_key;
      data.label = 'vortal.space';
      form.querySelectorAll('button').forEach(b => { b.disabled = true; });
      status(form, act === 'login' ? 'Signing in…' : 'Creating your account…', true);
      const out = await api('POST', act === 'login' ? '/api/account/login' : '/api/account/register', data);
      form.querySelectorAll('button').forEach(b => { b.disabled = false; });
      if (out.ok) {
        store.set({ token: out.token, username: out.username });
        return render(page);
      }
      if (out.error === 'reserved') form.querySelector('#acct-claim').hidden = false;
      status(form, out.message || 'That didn\'t work.');
    });
  }

  async function showMe(page, card, me) {
    card.innerHTML = signedInHTML(me);
    card.querySelector('#acct-out').addEventListener('click', async () => {
      await api('POST', '/api/account/logout');
      store.set(null);
      render(page, 'Signed out.');
    });
    const pw = card.querySelector('#acct-pw');
    pw.addEventListener('submit', async e => {
      e.preventDefault();
      const out = await api('POST', '/api/account/password', Object.fromEntries(new FormData(pw)));
      status(pw, out.ok ? 'Password changed. Other devices were signed out.' : (out.message || 'That didn\'t work.'), out.ok);
      if (out.ok) pw.reset();
    });
    const del = card.querySelector('#acct-del');
    del.addEventListener('submit', async e => {
      e.preventDefault();
      if (!confirm('Delete your Vortal account for good?')) return;
      const out = await api('POST', '/api/account/delete', Object.fromEntries(new FormData(del)));
      if (out.ok) { store.set(null); return render(page, 'Your account was deleted.'); }
      status(del, out.message || 'That didn\'t work.');
    });
    if (me.role === 'mod') moderation(card.querySelector('#acct-mods'));
  }

  async function moderation(box) {
    const out = await api('GET', '/api/volatile/bans');
    if (!out.ok) { box.innerHTML = `<h2>Moderation</h2><p class="acct__small">${esc(out.message || 'Couldn\'t load.')}</p>`; return; }
    const bans = out.bans || [];
    const log = out.log || [];
    box.innerHTML = `
      <h2>Moderation</h2>
      <p class="acct__small">Bans here block an account from online play on every server. In the game, <code>/ban name [minutes] [reason]</code> does the same and removes them from the game you're in.</p>
      <form class="cform acct__banform" id="acct-ban" novalidate>
        <div class="cform__row">
          <label class="cfield"><span>Username</span><input name="username" required maxlength="20"></label>
          <label class="cfield"><span>Minutes (blank = permanent)</span><input name="minutes" inputmode="numeric" maxlength="7"></label>
        </div>
        <label class="cfield"><span>Reason</span><input name="reason" maxlength="300"></label>
        <p class="cform__status" role="alert" hidden></p>
        <div class="acct__row"><button class="btn btn--solid" type="submit" data-act="ban">Ban</button><button class="btn btn--line" type="submit" data-act="unban">Unban</button></div>
      </form>
      <h3>Banned now (${bans.length})</h3>
      ${bans.length ? `<table class="acct__table"><thead><tr><th>Account</th><th>Until</th><th>By</th><th>Reason</th></tr></thead><tbody>${bans.map(b => `
        <tr><td>${esc(b.username)}</td><td>${b.ban_until ? esc(when(b.ban_until)) : 'permanent'}</td><td>${esc(b.banned_by)}</td><td>${esc(b.ban_reason)}</td></tr>`).join('')}</tbody></table>` : '<p class="acct__small">Nobody.</p>'}
      <h3>Recent actions</h3>
      ${log.length ? `<table class="acct__table"><thead><tr><th>When</th><th>Moderator</th><th>Action</th><th>Account</th><th>Note</th></tr></thead><tbody>${log.map(l => `
        <tr><td>${esc(when(l.at))}</td><td>${esc(l.moderator)}</td><td>${esc(l.action)}</td><td>${esc(l.target)}</td><td>${esc(l.reason)}</td></tr>`).join('')}</tbody></table>` : '<p class="acct__small">Nothing yet.</p>'}`;
    const form = box.querySelector('#acct-ban');
    let act = 'ban';
    form.querySelectorAll('button[type=submit]').forEach(b => b.addEventListener('click', () => { act = b.dataset.act; }));
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(form));
      const res = await api('POST', act === 'ban' ? '/api/volatile/ban' : '/api/volatile/unban',
        act === 'ban' ? { username: d.username, reason: d.reason, minutes: Number(d.minutes) || 0 } : { username: d.username });
      if (res.ok) return moderation(box);
      status(form, res.message || 'That didn\'t work.');
    });
  }

  window.VortalAccount = { render };
})();
