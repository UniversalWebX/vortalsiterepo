/* ═══════════════════════════════════════════════════════════════
   vortal.space Worker.
   The website is the static files in site/, served by Cloudflare's asset
   layer. This script only handles:
     POST /api/contact     the contact form → the inbox (D1)
     /api/admin/*          the private inbox panel at vortal.space/admin
     email()               mail that Email Routing sends here: saved to the
                           inbox, optionally forwarded, and auto-answered
   Every email feature is optional and stays off until its placeholder in
   wrangler.jsonc is filled in (see worker/README.md).
   ═══════════════════════════════════════════════════════════════ */
import { EmailMessage } from 'cloudflare:email';

const LIMITS = { name: 80, email: 200, topic: 40, subject: 200, body: 5000 };
const PER_HOUR = 5;              // contact-form messages per visitor per hour
const MIN_FILL_MS = 2500;        // a form filled faster than this is a bot
const ADMIN_TRIES = 10;          // wrong panel keys per visitor per 15 minutes
const PAGE = 50;                 // messages per page in the panel
const EMAIL_RE = /^[^\s@<>"(),;:]{1,64}@[^\s@<>"(),;:]{1,190}\.[A-Za-z]{2,24}$/;

const json = (status, body) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
});
// Trim, cap, and drop control characters (newlines are kept for message bodies).
const clean = (s, n) => String(s ?? '').replace(/\r\n?/g, '\n').replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '').trim().slice(0, n);
const oneLine = (s, n) => clean(s, n).replace(/\s+/g, ' ');

/* ---------- helpers ---------- */
async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return new Uint8Array(buf);
}
const hex = bytes => [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');

// Visitors are rate-limited by a hash of their IP, never the IP itself.
async function visitor(request, env) {
  const ip = request.headers.get('CF-Connecting-IP') || 'local';
  return hex((await sha256(`${env.IP_PEPPER || 'vortal.space'}|${ip}`)).slice(0, 12));
}

async function sameKey(given, expected) {
  const [a, b] = await Promise.all([sha256(given || ''), sha256(expected || '')]);
  return crypto.subtle.timingSafeEqual(a, b);
}

/* ---------- building emails (plain text, UTF-8) ---------- */
function base64Utf8(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin).replace(/.{1,76}/g, '$&\r\n');
}
const headerText = v => (/^[\x20-\x7E]*$/.test(v) ? v : `=?UTF-8?B?${base64Utf8(v).replace(/\r\n/g, '')}?=`);

function mime({ from, to, subject, text, replyTo, inReplyTo, references, auto }) {
  const domain = (/@([^>\s]+)/.exec(from) || [])[1] || 'vortal.space';
  const lines = [
    `From: ${from}`,
    `To: ${to}`,
    `Subject: ${headerText(oneLine(subject, LIMITS.subject))}`,
    `Date: ${new Date().toUTCString()}`,
    `Message-ID: <${crypto.randomUUID()}@${domain}>`,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    'Content-Transfer-Encoding: base64',
  ];
  if (replyTo) lines.push(`Reply-To: ${replyTo}`);
  if (inReplyTo) lines.push(`In-Reply-To: ${inReplyTo}`, `References: ${references || inReplyTo}`);
  if (auto) lines.push('Auto-Submitted: auto-replied');
  return `${lines.join('\r\n')}\r\n\r\n${base64Utf8(text)}`;
}

// Optional: email a copy of each contact-form message to you.
async function notify(env, m) {
  if (!env.NOTIFY || !env.NOTIFY_TO || !env.MAIL_FROM) return;
  const raw = mime({
    from: `Vortal inbox <${env.MAIL_FROM}>`,
    to: env.NOTIFY_TO,
    replyTo: m.email,
    subject: `[vortal.space] ${m.topic}: ${m.name}`,
    text: `${m.name} <${m.email}> wrote via the contact form (${m.topic}):\n\n${m.body}\n\n` +
      `Reply to this email to answer them, or open the inbox: https://vortal.space/admin`,
  });
  try {
    await env.NOTIFY.send(new EmailMessage(env.MAIL_FROM, env.NOTIFY_TO, raw));
  } catch (err) {
    console.log(`[notify] couldn't email message #${m.id}: ${err.message}`);
  }
}

/* ---------- reading incoming emails ---------- */
function splitHead(part) {
  const at = part.search(/\r?\n\r?\n/);
  return at < 0 ? [part, ''] : [part.slice(0, at), part.slice(at).replace(/^\r?\n\r?\n/, '')];
}
function decodeBody(head, body) {
  const enc = ((/content-transfer-encoding:\s*([\w-]+)/i.exec(head) || [])[1] || '').toLowerCase();
  if (enc !== 'base64' && enc !== 'quoted-printable') return body;      // already text
  const charset = (/charset="?([\w-]+)"?/i.exec(head) || [])[1] || 'utf-8';
  let bin;
  if (enc === 'base64') {
    try { bin = atob(body.replace(/\s+/g, '')); } catch { return body; }
  } else {
    bin = body.replace(/=\r?\n/g, '').replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
  }
  const bytes = Uint8Array.from(bin, ch => ch.charCodeAt(0) & 255);
  try { return new TextDecoder(charset).decode(bytes); } catch { return new TextDecoder().decode(bytes); }
}
function collectParts(raw, out, depth = 0) {
  const [head, body] = splitHead(raw);
  const type = (((/content-type:\s*([^;\r\n]+)/i.exec(head) || [])[1]) || 'text/plain').trim().toLowerCase();
  if (type.startsWith('multipart/') && depth < 5) {
    const boundary = (/boundary="?([^";\r\n]+)"?/i.exec(head) || [])[1];
    if (!boundary) return;
    for (const part of body.split(`--${boundary}`).slice(1)) {
      if (part.startsWith('--')) break;
      collectParts(part.replace(/^\r?\n/, ''), out, depth + 1);
    }
  } else if (type === 'text/plain' || type === 'text/html') {
    out.push({ type, text: decodeBody(head, body) });
  }
}
const stripHtml = html => html
  .replace(/<(style|script)[\s\S]*?<\/\1>/gi, '')
  .replace(/<br\s*\/?>|<\/p>|<\/div>/gi, '\n')
  .replace(/<[^>]+>/g, '')
  .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
  .replace(/\n{3,}/g, '\n\n');

function emailText(raw) {
  const parts = [];
  collectParts(raw, parts);
  const plain = parts.find(p => p.type === 'text/plain');
  if (plain) return plain.text;
  const html = parts.find(p => p.type === 'text/html');
  return html ? stripHtml(html.text) : '';
}

// Mailing lists, bounces and other robots never get an auto-reply (it would loop).
function isAutomated(message) {
  const h = name => (message.headers.get(name) || '').toLowerCase();
  if (h('auto-submitted') && h('auto-submitted') !== 'no') return true;
  if (/bulk|list|junk/.test(h('precedence'))) return true;
  if (h('list-id') || h('list-unsubscribe')) return true;
  return /(^|[^a-z])(no-?reply|mailer-daemon|postmaster|bounce)/i.test(message.from);
}

const AUTO_REPLY = `Hi,

Thanks for writing to Vortal. This is an automatic reply to say your message arrived.

A real person reads everything sent here and will answer as soon as they can, usually within a couple of days.

In the meantime, everything we make is at https://vortal.space

— Vortal`;

/* ---------- the contact form ---------- */
async function contact(request, env, ctx) {
  const origin = request.headers.get('Origin');
  if (origin && origin !== new URL(request.url).origin) return json(403, { error: 'origin' });
  let body;
  try { body = await request.json(); } catch { return json(400, { error: 'bad' }); }

  if (body.website) return json(200, { ok: true });                   // honeypot: act normal, save nothing
  const started = Number(body.started) || 0;
  if (!started || Date.now() - started < MIN_FILL_MS) return json(400, { error: 'fast' });

  const m = {
    name: oneLine(body.name, LIMITS.name),
    email: oneLine(body.email, LIMITS.email),
    topic: oneLine(body.topic, LIMITS.topic) || 'General',
    body: clean(body.message, LIMITS.body),
  };
  if (!m.name) return json(400, { error: 'name' });
  if (!EMAIL_RE.test(m.email)) return json(400, { error: 'email' });
  if (m.body.length < 10) return json(400, { error: 'message' });

  const who = await visitor(request, env);
  const recent = await env.DB.prepare('SELECT COUNT(*) AS n FROM messages WHERE ip_hash = ? AND created_at > ?')
    .bind(who, Date.now() - 3600e3).first('n');
  if (recent >= PER_HOUR) return json(429, { error: 'limit' });

  const saved = await env.DB.prepare(
    'INSERT INTO messages (created_at, source, name, email, topic, body, ip_hash, country, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind(Date.now(), 'form', m.name, m.email, m.topic, m.body, who, request.cf?.country || null,
    oneLine(request.headers.get('User-Agent'), 200) || null).run();
  m.id = saved.meta.last_row_id;
  console.log(`[contact] #${m.id} from ${m.name} (${m.topic})`);
  ctx.waitUntil(notify(env, m));
  return json(200, { ok: true, id: m.id });
}

/* ---------- the private panel ---------- */
const listed = r => ({
  id: r.id, created_at: r.created_at, source: r.source, name: r.name, email: r.email,
  topic: r.topic, subject: r.subject, snippet: r.snippet, status: r.status, country: r.country,
});

async function admin(request, env, url) {
  if (!env.ADMIN_KEY) return json(503, { error: 'nokey' });
  const who = await visitor(request, env);
  const now = Date.now();
  const tries = await env.DB.prepare('SELECT COUNT(*) AS n FROM admin_fails WHERE ip_hash = ? AND at > ?')
    .bind(who, now - 15 * 60e3).first('n');
  if (tries >= ADMIN_TRIES) return json(429, { error: 'locked' });

  const given = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (!(await sameKey(given, env.ADMIN_KEY))) {
    await env.DB.batch([
      env.DB.prepare('INSERT INTO admin_fails (ip_hash, at) VALUES (?, ?)').bind(who, now),
      env.DB.prepare('DELETE FROM admin_fails WHERE at < ?').bind(now - 86400e3),
    ]);
    return json(401, { error: 'key' });
  }

  const seg = url.pathname.split('/').filter(Boolean);        // ['api','admin',what,id]
  const what = seg[2], id = Number(seg[3]), method = request.method;

  if (what === 'overview' && method === 'GET') {
    const [byStatus, bySource, days] = await env.DB.batch([
      env.DB.prepare('SELECT status, COUNT(*) AS n FROM messages GROUP BY status'),
      env.DB.prepare('SELECT source, COUNT(*) AS n FROM messages GROUP BY source'),
      env.DB.prepare('SELECT CAST(created_at / 86400000 AS INTEGER) AS day, COUNT(*) AS n FROM messages WHERE created_at > ? GROUP BY day')
        .bind(now - 14 * 86400e3),
    ]);
    return json(200, {
      status: Object.fromEntries(byStatus.results.map(r => [r.status, r.n])),
      source: Object.fromEntries(bySource.results.map(r => [r.source, r.n])),
      days: days.results,
      today: Math.floor(now / 86400000),
      config: {
        notify: Boolean(env.NOTIFY && env.NOTIFY_TO && env.MAIL_FROM),
        notifyTo: env.NOTIFY_TO || '',
        mailFrom: env.MAIL_FROM || '',
        forwardTo: env.FORWARD_TO || '',
        autoReply: env.AUTO_REPLY !== 'off',
      },
    });
  }

  if (what === 'messages' && !seg[3] && method === 'GET') {
    const status = url.searchParams.get('status') || 'inbox';
    const source = url.searchParams.get('source');
    const q = (url.searchParams.get('q') || '').trim().slice(0, 100);
    const before = Number(url.searchParams.get('before')) || 0;
    const where = [], args = [];
    if (status === 'inbox') where.push("status != 'archived'");
    else if (['new', 'read', 'archived'].includes(status)) { where.push('status = ?'); args.push(status); }
    if (source === 'form' || source === 'email') { where.push('source = ?'); args.push(source); }
    if (q) {
      const like = `%${q.replace(/[\\%_]/g, c => `\\${c}`)}%`;
      where.push("(name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR subject LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR topic LIKE ? ESCAPE '\\')");
      args.push(like, like, like, like, like);
    }
    if (before) { where.push('id < ?'); args.push(before); }
    const { results } = await env.DB.prepare(
      `SELECT id, created_at, source, name, email, topic, subject, substr(body, 1, 180) AS snippet, status, country
       FROM messages ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY id DESC LIMIT ${PAGE + 1}`,
    ).bind(...args).all();
    return json(200, { rows: results.slice(0, PAGE).map(listed), more: results.length > PAGE });
  }

  if (what === 'messages' && Number.isInteger(id) && id > 0) {
    if (method === 'GET') {
      const row = await env.DB.prepare('SELECT * FROM messages WHERE id = ?').bind(id).first();
      if (!row) return json(404, { error: 'notfound' });
      delete row.ip_hash;
      return json(200, row);
    }
    if (method === 'PATCH') {
      const body = await request.json().catch(() => ({}));
      if (!['new', 'read', 'archived'].includes(body.status)) return json(400, { error: 'status' });
      await env.DB.prepare('UPDATE messages SET status = ? WHERE id = ?').bind(body.status, id).run();
      return json(200, { ok: true });
    }
    if (method === 'DELETE') {
      await env.DB.prepare('DELETE FROM messages WHERE id = ?').bind(id).run();
      return json(200, { ok: true });
    }
  }
  return json(404, { error: 'unknown' });
}

/* ---------- entry points ---------- */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
    try {
      if (url.pathname === '/api/contact' && request.method === 'POST') return await contact(request, env, ctx);
      if (url.pathname.startsWith('/api/admin/')) return await admin(request, env, url);
      if (url.pathname === '/api/health') return json(200, { ok: true });
      return json(404, { error: 'unknown' });
    } catch (err) {
      console.log(`[error] ${request.method} ${url.pathname}: ${err.stack || err.message}`);
      return json(500, { error: 'server' });
    }
  },

  // Mail routed here by Cloudflare Email Routing (e.g. contact@vortal.space).
  async email(message, env) {
    const fromHeader = message.headers.get('from') || message.from;
    const name = oneLine((/^\s*"?([^"<]*?)"?\s*</.exec(fromHeader) || [])[1] || message.from.split('@')[0], LIMITS.name);
    const subject = oneLine(message.headers.get('subject') || '(no subject)', LIMITS.subject);
    let text = '(This email was too large to show here; it was still forwarded if forwarding is on.)';
    if (message.rawSize < 5 * 1024 * 1024) text = clean(emailText(await new Response(message.raw).text()), LIMITS.body) || '(empty message)';

    await env.DB.prepare(
      'INSERT INTO messages (created_at, source, name, email, topic, subject, body) VALUES (?, ?, ?, ?, ?, ?, ?)',
    ).bind(Date.now(), 'email', name, message.from, 'Email', subject, text).run();
    console.log(`[email] from ${message.from}: ${subject}`);

    if (env.FORWARD_TO) {
      try { await message.forward(env.FORWARD_TO); } catch (err) { console.log(`[email] forward failed: ${err.message}`); }
    }
    if (env.AUTO_REPLY !== 'off' && !isAutomated(message)) {
      const id = message.headers.get('Message-ID');
      const raw = mime({
        from: `Vortal <${message.to}>`, to: message.from, subject: `Re: ${subject}`, text: AUTO_REPLY,
        inReplyTo: id, references: [message.headers.get('References'), id].filter(Boolean).join(' '), auto: true,
      });
      try { await message.reply(new EmailMessage(message.to, message.from, raw)); } catch (err) { console.log(`[email] auto-reply failed: ${err.message}`); }
    }
  },
};
