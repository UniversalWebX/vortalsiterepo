/* ═══════════════════════════════════════════════════════════════
   Vortal accounts. Volatile needs one for online play (solo doesn't).

     POST /api/account/register   {username, password, claim_key?}  → {token, username, role}
     POST /api/account/login      {username, password, label?}      → {token, username, role}
     GET  /api/account/me         (Bearer)                          → {username, role, created_at, ban}
     POST /api/account/logout     (Bearer)
     POST /api/account/password   (Bearer) {old, new}               → signs out every other device
     POST /api/account/delete     (Bearer) {password}

     POST /api/volatile/ticket    (Bearer) → {ticket}   a 2-minute, single-use join ticket
     POST /api/volatile/redeem    {ticket} → {username, role, ban}   what a game host calls
     POST /api/volatile/ban       (Bearer, moderator) {username, reason, minutes?}
     POST /api/volatile/unban     (Bearer, moderator) {username}
     GET  /api/volatile/bans      (Bearer, moderator)
     POST /api/volatile/log       (Bearer, moderator) {action, target, reason}   kicks/mutes for the record
     POST /api/volatile/servers   {name, port, world, players, max, version, build, protocol, dedicated, platform}
                                  a public server checking in (every minute; gone after 3 minutes of silence)
     GET  /api/volatile/servers   the public server list

   Sessions are random 32-byte tokens sent as "Authorization: Bearer …"; only
   their SHA-256 is stored. Players hand hosts a join ticket, never their
   session token, so a host can't take over their account.

   The usernames in RESERVED (VolatileDev, Darian by default) can only be
   registered with the site's ADMIN_KEY as claim_key, and they're moderators.
   ═══════════════════════════════════════════════════════════════ */

const ITER = 100000;                       // PBKDF2 rounds (Workers' maximum)
const TICKET_MS = 2 * 60 * 1000;
const NAME_RE = /^[A-Za-z0-9_]{3,20}$/;
const FAILS = 10;                          // wrong passwords per visitor+name per 15 minutes
const SIGNUPS = 5;                         // new accounts per visitor per hour

export const json = (status, body) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*' },
});
const hex = bytes => [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('');
const sha = async text => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
const randomToken = () => {
  const b = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

async function hashPassword(password, saltHex, iter) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']);
  const salt = new Uint8Array(saltHex.match(/../g).map(h => parseInt(h, 16)));
  return hex(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iter }, key, 256));
}

async function sameText(a, b) {
  const [x, y] = await Promise.all([sha(a || ''), sha(b || '')]);
  const enc = new TextEncoder();
  return crypto.subtle.timingSafeEqual(enc.encode(x), enc.encode(y));
}

const reserved = env => String(env.RESERVED || 'VolatileDev,Darian').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);

export async function visitorKey(request, env) {
  const ip = request.headers.get('CF-Connecting-IP') || 'local';
  return (await sha(`${env.IP_PEPPER || 'vortal.space'}|${ip}`)).slice(0, 24);
}

async function tooMany(env, key, limit, windowMs) {
  const n = await env.DB.prepare('SELECT COUNT(*) AS n FROM account_fails WHERE key = ? AND at > ?').bind(key, Date.now() - windowMs).first('n');
  return n >= limit;
}
const fail = (env, key) => env.DB.prepare('INSERT INTO account_fails (key, at) VALUES (?, ?)').bind(key, Date.now()).run();

export function banInfo(a) {
  if (!a.banned_at) return null;
  if (a.ban_until && a.ban_until < Date.now()) return null;       // expired
  return { reason: a.ban_reason || '', until: a.ban_until || null, by: a.banned_by || '' };
}

async function newSession(env, account, label) {
  const token = randomToken();
  const now = Date.now();
  await env.DB.prepare('INSERT INTO sessions (token_hash, account_id, created_at, last_used, label) VALUES (?, ?, ?, ?, ?)')
    .bind(await sha(token), account.id, now, now, String(label || '').slice(0, 60)).run();
  return token;
}

// The signed-in account for this request, or null.
export async function authed(request, env) {
  const m = /^Bearer\s+(\S+)$/.exec(request.headers.get('Authorization') || '');
  if (!m) return null;
  const th = await sha(m[1]);
  const row = await env.DB.prepare('SELECT a.*, s.token_hash AS th FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.token_hash = ?').bind(th).first();
  if (!row) return null;
  await env.DB.prepare('UPDATE sessions SET last_used = ? WHERE token_hash = ?').bind(Date.now(), th).run();
  return row;
}

const pub = a => ({ username: a.username, role: a.role, created_at: a.created_at, ban: banInfo(a) });
export const byName = (env, name) => env.DB.prepare('SELECT * FROM accounts WHERE username_key = ?').bind(String(name || '').toLowerCase()).first();
export const log = (env, mod, action, target, reason) => env.DB.prepare('INSERT INTO mod_log (at, moderator, action, target, reason) VALUES (?, ?, ?, ?, ?)')
  .bind(Date.now(), mod, action, String(target || '').slice(0, 40), String(reason || '').slice(0, 300)).run();

async function body(request) {
  try { return await request.json(); } catch { return {}; }
}

/* ---------- account endpoints ---------- */
async function register(request, env) {
  const b = await body(request);
  const username = String(b.username || '').trim();
  const password = String(b.password || '');
  if (!NAME_RE.test(username)) return json(400, { error: 'username', message: 'Usernames are 3–20 letters, numbers or underscores.' });
  if (password.length < 8 || password.length > 200) return json(400, { error: 'password', message: 'Passwords need at least 8 characters.' });
  const who = `signup|${await visitorKey(request, env)}`;
  if (await tooMany(env, who, SIGNUPS, 3600e3)) return json(429, { error: 'limit', message: 'Too many new accounts from here. Try again in an hour.' });
  const key = username.toLowerCase();
  let role = 'player';
  if (reserved(env).includes(key)) {
    if (!env.ADMIN_KEY || !(await sameText(String(b.claim_key || ''), env.ADMIN_KEY))) {
      return json(403, { error: 'reserved', message: 'That name is reserved.' });
    }
    role = 'mod';
  }
  if (await byName(env, username)) return json(409, { error: 'taken', message: 'That username is taken.' });
  const salt = hex(crypto.getRandomValues(new Uint8Array(16)));
  const hash = await hashPassword(password, salt, ITER);
  await fail(env, who);   // counts toward the sign-up limit
  const res = await env.DB.prepare('INSERT INTO accounts (username, username_key, pass_hash, pass_salt, pass_iter, role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .bind(username, key, hash, salt, ITER, role, Date.now()).run();
  const account = { id: res.meta.last_row_id, username, role };
  const token = await newSession(env, account, b.label);
  console.log(`[account] new ${username} (${role})`);
  return json(200, { ok: true, token, username, role });
}

async function login(request, env) {
  const b = await body(request);
  const a = await byName(env, b.username);
  const who = `login|${await visitorKey(request, env)}|${String(b.username || '').toLowerCase()}`;
  if (await tooMany(env, who, FAILS, 15 * 60e3)) return json(429, { error: 'limit', message: 'Too many wrong passwords. Wait 15 minutes and try again.' });
  if (!a || (await hashPassword(String(b.password || ''), a.pass_salt, a.pass_iter)) !== a.pass_hash) {
    await fail(env, who);
    return json(401, { error: 'wrong', message: 'Wrong username or password.' });
  }
  const token = await newSession(env, a, b.label);
  return json(200, { ok: true, token, username: a.username, role: a.role, ban: banInfo(a) });
}

async function changePassword(request, env, a) {
  const b = await body(request);
  if ((await hashPassword(String(b.old || ''), a.pass_salt, a.pass_iter)) !== a.pass_hash) return json(401, { error: 'wrong', message: 'Your current password is wrong.' });
  const pw = String(b.new || '');
  if (pw.length < 8 || pw.length > 200) return json(400, { error: 'password', message: 'Passwords need at least 8 characters.' });
  const salt = hex(crypto.getRandomValues(new Uint8Array(16)));
  await env.DB.prepare('UPDATE accounts SET pass_hash = ?, pass_salt = ?, pass_iter = ? WHERE id = ?').bind(await hashPassword(pw, salt, ITER), salt, ITER, a.id).run();
  await env.DB.prepare('DELETE FROM sessions WHERE account_id = ? AND token_hash != ?').bind(a.id, a.th).run();
  return json(200, { ok: true });
}

async function deleteAccount(request, env, a) {
  const b = await body(request);
  if ((await hashPassword(String(b.password || ''), a.pass_salt, a.pass_iter)) !== a.pass_hash) return json(401, { error: 'wrong', message: 'Wrong password.' });
  if (banInfo(a)) return json(403, { error: 'banned', message: "Banned accounts can't be deleted." });
  await env.DB.batch([
    env.DB.prepare('DELETE FROM sessions WHERE account_id = ?').bind(a.id),
    env.DB.prepare('DELETE FROM tickets WHERE account_id = ?').bind(a.id),
    env.DB.prepare('DELETE FROM accounts WHERE id = ?').bind(a.id),
  ]);
  return json(200, { ok: true });
}

/* ---------- Volatile: joining games, moderation ---------- */
async function ticket(env, a) {
  const ban = banInfo(a);
  if (ban) return json(403, { error: 'banned', message: banText(ban), ban });
  const t = randomToken();
  await env.DB.prepare('DELETE FROM tickets WHERE expires_at < ?').bind(Date.now()).run();
  await env.DB.prepare('INSERT INTO tickets (ticket_hash, account_id, expires_at) VALUES (?, ?, ?)').bind(await sha(t), a.id, Date.now() + TICKET_MS).run();
  return json(200, { ok: true, ticket: t, expires_in: TICKET_MS / 1000 });
}

const banText = ban => `This account is banned from online play${ban.until ? ` until ${new Date(ban.until).toUTCString()}` : ''}${ban.reason ? `: ${ban.reason}` : '.'}`;

async function redeem(request, env) {
  const b = await body(request);
  const th = await sha(String(b.ticket || ''));
  const row = await env.DB.prepare('SELECT a.* FROM tickets t JOIN accounts a ON a.id = t.account_id WHERE t.ticket_hash = ? AND t.expires_at > ?').bind(th, Date.now()).first();
  await env.DB.prepare('DELETE FROM tickets WHERE ticket_hash = ?').bind(th).run();    // single use
  if (!row) return json(404, { error: 'ticket', message: 'That sign-in ticket is invalid or expired.' });
  return json(200, { ok: true, ...pub(row) });
}

async function ban(request, env, mod) {
  const b = await body(request);
  const t = await byName(env, b.username);
  if (!t) return json(404, { error: 'unknown', message: 'No account with that name.' });
  if (t.role === 'mod') return json(403, { error: 'mod', message: "Moderators can't be banned." });
  const minutes = Number(b.minutes) || 0;
  const until = minutes > 0 ? Date.now() + minutes * 60e3 : null;
  const reason = String(b.reason || '').slice(0, 300);
  await env.DB.prepare('UPDATE accounts SET banned_at = ?, ban_until = ?, ban_reason = ?, banned_by = ? WHERE id = ?').bind(Date.now(), until, reason, mod.username, t.id).run();
  await env.DB.prepare('DELETE FROM tickets WHERE account_id = ?').bind(t.id).run();
  await log(env, mod.username, 'ban', t.username, `${reason}${minutes > 0 ? ` (${minutes} min)` : ''}`);
  return json(200, { ok: true, username: t.username, until });
}

async function unban(request, env, mod) {
  const b = await body(request);
  const t = await byName(env, b.username);
  if (!t) return json(404, { error: 'unknown', message: 'No account with that name.' });
  await env.DB.prepare('UPDATE accounts SET banned_at = NULL, ban_until = NULL, ban_reason = NULL, banned_by = NULL WHERE id = ?').bind(t.id).run();
  await log(env, mod.username, 'unban', t.username, '');
  return json(200, { ok: true, username: t.username });
}

async function bans(env) {
  const r = await env.DB.prepare('SELECT username, banned_at, ban_until, ban_reason, banned_by FROM accounts WHERE banned_at IS NOT NULL AND (ban_until IS NULL OR ban_until > ?) ORDER BY banned_at DESC LIMIT 200').bind(Date.now()).all();
  const l = await env.DB.prepare('SELECT at, moderator, action, target, reason FROM mod_log ORDER BY at DESC LIMIT 50').all();
  return json(200, { ok: true, bans: r.results, log: l.results });
}

/* ---------- the public server list ---------- */
const SERVER_TTL = 3 * 60 * 1000;
const SERVERS_PER_IP = 3;
const cut = (v, n) => String(v ?? '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, n);

async function heartbeat(request, env) {
  const b = await body(request);
  const ip = request.headers.get('CF-Connecting-IP') || '';
  const port = Number(b.port) | 0;
  if (!ip || port < 1 || port > 65535) return json(400, { error: 'address', message: 'Bad port.' });
  const address = ip.includes(':') ? `[${ip}]:${port}` : `${ip}:${port}`;
  const ipHash = await visitorKey(request, env);
  const now = Date.now();
  await env.DB.prepare('DELETE FROM servers WHERE last_seen < ?').bind(now - SERVER_TTL).run();
  const mine = await env.DB.prepare('SELECT COUNT(*) AS n FROM servers WHERE ip_hash = ? AND address != ?').bind(ipHash, address).first('n');
  if (mine >= SERVERS_PER_IP) return json(429, { error: 'limit', message: `At most ${SERVERS_PER_IP} public servers per address.` });
  const name = cut(b.name, 48) || 'Volatile server';
  await env.DB.prepare(`INSERT INTO servers (address, ip_hash, name, world, players, max_players, version, build, protocol, dedicated, platform, last_seen)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(address) DO UPDATE SET name = excluded.name, world = excluded.world, players = excluded.players, max_players = excluded.max_players,
        version = excluded.version, build = excluded.build, protocol = excluded.protocol, dedicated = excluded.dedicated, platform = excluded.platform, last_seen = excluded.last_seen`)
    .bind(address, ipHash, name, cut(b.world, 48), Math.max(0, Math.min(64, Number(b.players) | 0)), Math.max(1, Math.min(64, Number(b.max) | 0 || 8)),
      cut(b.version, 24), Number(b.build) | 0, Number(b.protocol) | 0, b.dedicated ? 1 : 0, cut(b.platform, 16), now).run();
  return json(200, { ok: true, address });
}

async function serverList(env) {
  const r = await env.DB.prepare('SELECT address, name, world, players, max_players, version, build, protocol, dedicated, platform, last_seen FROM servers WHERE last_seen > ? ORDER BY players DESC, last_seen DESC LIMIT 100')
    .bind(Date.now() - SERVER_TTL).all();
  return json(200, { ok: true, servers: r.results });
}

/* ---------- routing ---------- */
export async function accounts(request, env, url) {
  const p = url.pathname;
  const m = request.method;
  if (m === 'OPTIONS') {
    return new Response(null, { status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST', 'Access-Control-Allow-Headers': 'Authorization, Content-Type' } });
  }
  if (p === '/api/account/register' && m === 'POST') return register(request, env);
  if (p === '/api/account/login' && m === 'POST') return login(request, env);
  if (p === '/api/volatile/redeem' && m === 'POST') return redeem(request, env);
  if (p === '/api/volatile/servers' && m === 'POST') return heartbeat(request, env);
  if (p === '/api/volatile/servers' && m === 'GET') return serverList(env);
  const a = await authed(request, env);
  if (!a) return json(401, { error: 'signin', message: 'Please sign in again.' });
  if (p === '/api/account/me') return json(200, { ok: true, ...pub(a) });
  if (p === '/api/account/logout' && m === 'POST') {
    await env.DB.prepare('DELETE FROM sessions WHERE token_hash = ?').bind(a.th).run();
    return json(200, { ok: true });
  }
  if (p === '/api/account/password' && m === 'POST') return changePassword(request, env, a);
  if (p === '/api/account/delete' && m === 'POST') return deleteAccount(request, env, a);
  if (p === '/api/volatile/ticket' && m === 'POST') return ticket(env, a);
  if (a.role !== 'mod') return json(403, { error: 'mod', message: 'Moderators only.' });
  if (p === '/api/volatile/ban' && m === 'POST') return ban(request, env, a);
  if (p === '/api/volatile/unban' && m === 'POST') return unban(request, env, a);
  if (p === '/api/volatile/bans') return bans(env);
  if (p === '/api/volatile/log' && m === 'POST') {
    const b = await body(request);
    await log(env, a.username, String(b.action || 'note').slice(0, 20), b.target, b.reason);
    return json(200, { ok: true });
  }
  return json(404, { error: 'unknown' });
}
