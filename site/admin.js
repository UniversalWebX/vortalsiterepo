/* Vortal inbox: the private panel at vortal.space/admin.
   Talks to /api/admin/* with the key set by `wrangler secret put ADMIN_KEY`. */
(() => {
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const KEY = 'vortal.inboxKey';
  const S = { key: null, status: 'inbox', source: '', q: '', rows: [], more: false, openId: null, open: null, overview: null, busy: false };

  /* ---------- key storage ---------- */
  const saved = () => { try { return sessionStorage.getItem(KEY) || localStorage.getItem(KEY); } catch { return null; } };
  const keep = (k, remember) => { try { sessionStorage.setItem(KEY, k); if (remember) localStorage.setItem(KEY, k); } catch { /* storage blocked */ } };
  const forget = () => { try { sessionStorage.removeItem(KEY); localStorage.removeItem(KEY); } catch { /* storage blocked */ } };

  let toastTimer = 0;
  function toast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  async function api(path, opts = {}) {
    const res = await fetch(`/api/admin/${path}`, {
      method: opts.method || 'GET',
      headers: { Authorization: `Bearer ${S.key}`, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(data.error || 'network'), { status: res.status });
    return data;
  }

  const LOGIN_ERRORS = {
    key: "That key doesn't match. Check it and try again.",
    locked: 'Too many wrong keys from this network. Wait 15 minutes and try again.',
    nokey: 'The inbox key isn\'t set yet. In the repo folder run <code>npx wrangler secret put ADMIN_KEY</code>, then come back.',
    network: "Can't reach vortal.space. Check your connection.",
  };

  /* ---------- time ---------- */
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  function ago(ms) {
    const s = (ms - Date.now()) / 1000;
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [unit, size] of units) if (Math.abs(s) >= size) return rtf.format(Math.round(s / size), unit);
    return 'just now';
  }
  const fullDate = ms => new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

  /* ---------- login ---------- */
  async function unlock(key, remember) {
    S.key = key;
    const btn = $('#unlockBtn');
    btn.disabled = true;
    btn.textContent = 'Unlocking…';
    try {
      S.overview = await api('overview');
      keep(key, remember);
      showPanel();
    } catch (err) {
      S.key = null;
      if (err.message !== 'key' || !remember) forget();
      const el = $('#loginError');
      el.innerHTML = LOGIN_ERRORS[err.message] || LOGIN_ERRORS.network;
      el.hidden = false;
      $('#keyInput').select();
    } finally {
      btn.disabled = false;
      btn.textContent = 'Unlock';
    }
  }

  function lock() {
    forget();
    clearInterval(pollTimer);
    Object.assign(S, { key: null, rows: [], open: null, openId: null, overview: null });
    $('#panel').hidden = true;
    $('#barActions').hidden = true;
    $('#login').hidden = false;
    $('#keyInput').value = '';
    $('#keyInput').focus();
    document.title = 'Vortal Inbox';
  }

  function showPanel() {
    $('#login').hidden = true;
    $('#panel').hidden = false;
    $('#barActions').hidden = false;
    renderOverview();
    loadList();
    clearInterval(pollTimer);
    pollTimer = setInterval(() => { if (!document.hidden) refresh(true); }, 30000);
  }

  /* ---------- overview ---------- */
  function renderOverview() {
    const o = S.overview;
    if (!o) return;
    const n = o.status.new || 0;
    $('#statNew').textContent = n;
    $('#statInbox').textContent = (o.status.new || 0) + (o.status.read || 0);
    document.title = n ? `(${n}) Vortal Inbox` : 'Vortal Inbox';

    const counts = new Map(o.days.map(d => [d.day, d.n]));
    const days = Array.from({ length: 14 }, (_, i) => counts.get(o.today - 13 + i) || 0);
    const max = Math.max(1, ...days), total = days.reduce((a, b) => a + b, 0);
    $('#spark').innerHTML = days.map((v, i) => {
      const h = v ? Math.max(3, (v / max) * 32) : 1.5;
      return `<rect x="${i * 10 + 1}" y="${34 - h}" width="8" height="${h}" rx="1" fill="${i === 13 ? '#D5B2FF' : v ? '#A259FF' : '#3B2F59'}"><title>${v} message${v === 1 ? '' : 's'}</title></rect>`;
    }).join('');
    $('#sparkLabel').textContent = `${total} in the last 14 days`;
  }

  /* ---------- the list ---------- */
  async function loadList(append = false) {
    if (S.busy) return;
    S.busy = true;
    const params = new URLSearchParams({ status: S.status });
    if (S.source) params.set('source', S.source);
    if (S.q) params.set('q', S.q);
    if (append && S.rows.length) params.set('before', S.rows[S.rows.length - 1].id);
    try {
      const data = await api(`messages?${params}`);
      S.rows = append ? S.rows.concat(data.rows) : data.rows;
      S.more = data.more;
      renderList();
      $('#sync').textContent = `Updated ${new Date().toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`;
    } catch (err) {
      if (err.message === 'key' || err.message === 'locked') { lock(); return; }
      toast("Couldn't load messages. Trying again shortly.");
    } finally {
      S.busy = false;
    }
  }

  function renderList() {
    const ul = $('#rows');
    ul.innerHTML = S.rows.map(r => `
      <li><button type="button" class="arow is-${r.status}" data-id="${r.id}" aria-current="${r.id === S.openId}">
        <span class="arow__dot" aria-hidden="true"></span>
        <span class="arow__who">${esc(r.name || r.email || 'Unknown')}</span>
        <span class="arow__time" title="${esc(fullDate(r.created_at))}">${esc(ago(r.created_at))}</span>
        <span class="arow__line"><span class="arow__tag">${esc(r.source === 'email' ? 'Email' : r.topic || 'Form')}</span>${esc(r.subject ? `${r.subject} — ${r.snippet}` : r.snippet)}</span>
      </button></li>`).join('');
    const empty = $('#listEmpty');
    empty.hidden = S.rows.length > 0;
    empty.textContent = S.q ? `Nothing matches “${S.q}”.` : S.status === 'archived' ? 'Nothing archived yet.' : S.status === 'new' ? 'No new messages. All caught up.' : 'No messages yet. They appear here as soon as someone uses the contact form.';
    $('#moreBtn').hidden = !S.more;
  }

  async function refresh(quiet = false) {
    try {
      S.overview = await api('overview');
      renderOverview();
      if (!S.q) await loadList();
      if (!quiet) toast('Up to date');
    } catch (err) {
      if (err.message === 'key' || err.message === 'locked') lock();
    }
  }

  /* ---------- one message ---------- */
  async function openMessage(id) {
    S.openId = id;
    renderList();
    $('#panel').classList.add('show-detail');
    try {
      const m = await api(`messages/${id}`);
      S.open = m;
      renderMessage();
      if (m.status === 'new') await setStatus('read', true);
    } catch {
      $('#detail').innerHTML = '<div class="aplaceholder"><p>That message couldn\'t be loaded. It may have been deleted.</p></div>';
    }
  }

  function replyLink(m) {
    const subject = m.subject ? `Re: ${m.subject}` : `Re: your message to Vortal${m.topic && m.topic !== 'General' ? ` (${m.topic})` : ''}`;
    const quoted = m.body.length > 1200 ? `${m.body.slice(0, 1200)}…` : m.body;
    const body = `\n\n—\nOn ${fullDate(m.created_at)}, ${m.name || m.email} wrote:\n> ${quoted.split('\n').join('\n> ')}`;
    return `mailto:${encodeURIComponent(m.email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  function renderMessage() {
    const m = S.open;
    if (!m) return;
    $('#detail').innerHTML = `
      <article class="amsg">
        <button type="button" class="abtn amsg__back" data-act="back">← All messages</button>
        <div class="amsg__meta">
          <span>#${m.id}</span><span>${m.source === 'email' ? 'Email' : 'Contact form'}</span>
          ${m.topic ? `<span>${esc(m.topic)}</span>` : ''}
          <span title="${esc(ago(m.created_at))}">${esc(fullDate(m.created_at))}</span>
          ${m.country ? `<span>${esc(m.country)}</span>` : ''}
          <span>${m.status === 'archived' ? 'Archived' : m.status === 'new' ? 'New' : 'Read'}</span>
        </div>
        <h2>${esc(m.name || 'Unknown sender')}</h2>
        <p class="amsg__from"><a href="mailto:${esc(m.email)}">${esc(m.email)}</a>
          <button type="button" class="abtn" data-act="copy">Copy email</button></p>
        ${m.subject ? `<p class="amsg__subject">${esc(m.subject)}</p>` : ''}
        <div class="amsg__body">${esc(m.body)}</div>
        <div class="amsg__actions">
          <a class="btn btn--solid" href="${esc(replyLink(m))}" data-act="reply">Reply by email</a>
          ${m.status === 'archived'
            ? '<button type="button" class="abtn" data-act="inbox">Move to inbox</button>'
            : '<button type="button" class="abtn" data-act="archive">Archive</button>'}
          ${m.status !== 'new' ? '<button type="button" class="abtn" data-act="unread">Mark unread</button>' : ''}
          <button type="button" class="abtn abtn--danger" data-act="delete">Delete</button>
        </div>
        ${m.user_agent ? `<p class="amsg__tech">Browser: ${esc(m.user_agent)}</p>` : ''}
      </article>`;
  }

  async function setStatus(status, quiet = false) {
    const m = S.open;
    if (!m) return;
    try {
      await api(`messages/${m.id}`, { method: 'PATCH', body: { status } });
      m.status = status;
      const row = S.rows.find(r => r.id === m.id);
      if (row) row.status = status;
      if (status === 'archived' && S.status !== 'archived' && S.status !== 'all') {
        S.rows = S.rows.filter(r => r.id !== m.id);
        closeMessage();
      } else {
        renderMessage();
      }
      renderList();
      S.overview = await api('overview');
      renderOverview();
      if (!quiet) toast(status === 'archived' ? 'Archived' : status === 'new' ? 'Marked unread' : 'Moved to the inbox');
    } catch {
      toast("Couldn't update that message. Try again.");
    }
  }

  async function remove() {
    const m = S.open;
    if (!m || !confirm(`Delete the message from ${m.name || m.email}? This can't be undone.`)) return;
    try {
      await api(`messages/${m.id}`, { method: 'DELETE' });
      S.rows = S.rows.filter(r => r.id !== m.id);
      closeMessage();
      renderList();
      S.overview = await api('overview');
      renderOverview();
      toast('Deleted');
    } catch {
      toast("Couldn't delete that message. Try again.");
    }
  }

  function closeMessage() {
    S.open = null;
    S.openId = null;
    $('#panel').classList.remove('show-detail');
    $('#detail').innerHTML = '<div class="aplaceholder"><p>Pick a message to read it.</p></div>';
  }

  /* ---------- email setup dialog ---------- */
  function openSetup() {
    const c = (S.overview && S.overview.config) || {};
    const item = (on, title, detail) =>
      `<li><span class="${on ? 'is-on' : 'is-off'}" aria-hidden="true">${on ? '●' : '○'}</span><span>${title}<small>${detail}</small></span></li>`;
    $('#checklist').innerHTML = [
      item(true, 'Contact form → this inbox', 'Always on. Messages from vortal.space/contact land here.'),
      item(c.notify, 'Email copy of each form message', c.notify ? `Sent to ${esc(c.notifyTo)} from ${esc(c.mailFrom)}.` : 'Off: set MAIL_FROM and NOTIFY_TO, and uncomment send_email.'),
      item(Boolean(c.forwardTo), 'Forward contact@vortal.space', c.forwardTo ? `Forwarded to ${esc(c.forwardTo)}, and saved here.` : 'Off: set FORWARD_TO, and route the address to this Worker in Email Routing.'),
      item(c.autoReply, 'Automatic reply to emails', c.autoReply ? 'On: anyone who emails the routed address gets a "we got your message" reply.' : 'Off: AUTO_REPLY is "off".'),
    ].join('');
    $('#setupDialog').showModal();
  }

  /* ---------- wiring ---------- */
  let pollTimer = 0, searchTimer = 0;
  $('#loginForm').addEventListener('submit', e => {
    e.preventDefault();
    const key = $('#keyInput').value.trim();
    if (key) unlock(key, $('#remember').checked);
  });
  $('#lockBtn').addEventListener('click', lock);
  $('#refreshBtn').addEventListener('click', () => refresh());
  $('#setupBtn').addEventListener('click', openSetup);
  $('#moreBtn').addEventListener('click', () => loadList(true));

  $('#statusSeg').addEventListener('click', e => {
    const b = e.target.closest('[data-status]');
    if (!b) return;
    S.status = b.dataset.status;
    $('#statusSeg').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    loadList();
  });
  $('#sourceSeg').addEventListener('click', e => {
    const b = e.target.closest('[data-source]');
    if (!b) return;
    S.source = b.dataset.source;
    $('#sourceSeg').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    loadList();
  });
  $('#search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { S.q = e.target.value.trim(); loadList(); }, 250);
  });
  $('#rows').addEventListener('click', e => {
    const b = e.target.closest('[data-id]');
    if (b) openMessage(Number(b.dataset.id));
  });
  $('#detail').addEventListener('click', async e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'back') closeMessage();
    else if (act === 'archive') setStatus('archived');
    else if (act === 'inbox') setStatus('read');
    else if (act === 'unread') setStatus('new');
    else if (act === 'delete') remove();
    else if (act === 'copy') {
      try { await navigator.clipboard.writeText(S.open.email); toast('Email copied'); } catch { toast(S.open.email); }
    }
  });

  document.addEventListener('keydown', e => {
    if ($('#panel').hidden || e.target.closest('input, textarea, dialog') || e.metaKey || e.ctrlKey || e.altKey) return;
    const i = S.rows.findIndex(r => r.id === S.openId);
    if (e.key === 'j' || e.key === 'k') {
      const next = S.rows[Math.min(S.rows.length - 1, Math.max(0, i + (e.key === 'j' ? 1 : -1)))] || S.rows[0];
      if (next) { openMessage(next.id); document.querySelector(`[data-id="${next.id}"]`)?.scrollIntoView({ block: 'nearest' }); }
    } else if (e.key === '/') {
      e.preventDefault();
      $('#search').focus();
    } else if (S.open && e.key === 'e') setStatus(S.open.status === 'archived' ? 'read' : 'archived');
    else if (S.open && e.key === 'u') setStatus('new');
    else if (S.open && e.key === 'r') location.href = replyLink(S.open);
    else if (e.key === 'Escape' && S.open) closeMessage();
  });

  const remembered = saved();
  if (remembered) unlock(remembered, true); else $('#keyInput').focus();
})();
