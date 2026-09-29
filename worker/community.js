/* ═══════════════════════════════════════════════════════════════
   vortal.space community: the launch chat and announcements.
   Chat opens when Volatile 1.0 does (CHAT_OPENS, October 1, 5:30 PM
   Pacific); moderators can post before that to test. Posting needs a
   Vortal account (accounts.js); reading doesn't.

     GET  /api/community/feed?after=ID&since=MS   announcements, chat messages
                                                   newer than ID, and ids deleted
                                                   since MS (pages poll this)
     POST /api/community/chat        (Bearer) {body}
     POST /api/community/delete      (Bearer, moderator) {id}
     POST /api/community/mute        (Bearer, moderator) {username, minutes, reason}   minutes 0 = unmute
     POST /api/community/announce    (Bearer, moderator) {title, body, link, pinned, at?}
     POST /api/community/unannounce  (Bearer, moderator) {id}
   ═══════════════════════════════════════════════════════════════ */
import { json, authed, banInfo, byName, log } from './accounts.js';

const MAX_LEN = 300;
const HISTORY = 60;                  // messages a page gets when it first opens
const KEEP_DAYS = 30;                // older chat is pruned
const opensAt = env => Date.parse(env.CHAT_OPENS || '2026-10-01T17:30:00-07:00');

const clean = (v, n) => String(v ?? '').replace(/[\u0000-\u0008\u000b-\u001f\u007f​-‏‪-‮⁦-⁩]/g, '')
  .replace(/\s+/g, ' ').trim().slice(0, n);
const safeLink = v => {
  const s = String(v ?? '').trim();
  return /^https:\/\/[^\s]+$/i.test(s) || /^\/(?!\/)[^\s]*$/.test(s) ? s.slice(0, 300) : '';
};

async function body(request) {
  try { return await request.json(); } catch { return {}; }
}

async function muteOf(env, a) {
  const m = await env.DB.prepare('SELECT until, reason FROM chat_mutes WHERE account_id = ?').bind(a.id).first();
  if (!m) return null;
  if (m.until && m.until < Date.now()) {
    await env.DB.prepare('DELETE FROM chat_mutes WHERE account_id = ?').bind(a.id).run();
    return null;
  }
  return m;
}

const msgOut = m => ({ id: m.id, at: m.at, username: m.username, role: m.role, body: m.body });

async function feed(request, env, url) {
  const now = Date.now();
  const opens = opensAt(env);
  const a = request.headers.get('Authorization') ? await authed(request, env) : null;
  const mod = !!(a && a.role === 'mod');
  const open = now >= opens;
  const ann = await env.DB.prepare(
    'SELECT id, at, author, title, body, link, pinned FROM announcements WHERE deleted_at IS NULL AND at <= ? ORDER BY pinned DESC, at DESC LIMIT 10').bind(now).all();
  const out = { ok: true, now, opens_at: opens, open, announcements: ann.results, messages: [], deleted: [] };
  if (a) {
    out.me = { username: a.username, role: a.role, ban: banInfo(a), mute: await muteOf(env, a) };
  }
  if (url.searchParams.get('lite')) return json(200, out);
  if (open || mod) {
    const after = Number(url.searchParams.get('after')) || 0;
    const rows = after > 0
      ? await env.DB.prepare('SELECT * FROM chat_messages WHERE id > ? AND deleted_at IS NULL ORDER BY id LIMIT 100').bind(after).all()
      : await env.DB.prepare('SELECT * FROM (SELECT * FROM chat_messages WHERE deleted_at IS NULL ORDER BY id DESC LIMIT ?) ORDER BY id').bind(HISTORY).all();
    out.messages = rows.results.map(msgOut);
    const since = Number(url.searchParams.get('since')) || 0;
    if (since > 0) {
      const d = await env.DB.prepare('SELECT id FROM chat_messages WHERE deleted_at > ? LIMIT 200').bind(since).all();
      out.deleted = d.results.map(r => r.id);
    }
  }
  return json(200, out);
}

async function post(request, env, ctx, a) {
  const ban = banInfo(a);
  if (ban) return json(403, { error: 'banned', message: 'This account is banned.' });
  const mute = await muteOf(env, a);
  if (mute) return json(403, { error: 'muted', message: `You're muted in the chat${mute.until ? ` until ${new Date(mute.until).toUTCString()}` : ''}${mute.reason ? `: ${mute.reason}` : '.'}`, mute });
  if (Date.now() < opensAt(env) && a.role !== 'mod') return json(403, { error: 'closed', message: 'The chat opens when Volatile 1.0 comes out.' });
  const text = clean((await body(request)).body, MAX_LEN);
  if (!text) return json(400, { error: 'empty', message: 'Write something first.' });
  const now = Date.now();
  if (a.role !== 'mod') {
    const recent = await env.DB.prepare('SELECT at, body FROM chat_messages WHERE account_id = ? AND at > ? ORDER BY at DESC LIMIT 12').bind(a.id, now - 60e3).all();
    const r = recent.results;
    if (r.length && now - r[0].at < 2000) return json(429, { error: 'slow', message: 'Slow down a little.' });
    if (r.length >= 10) return json(429, { error: 'slow', message: 'That\'s a lot of messages. Wait a minute.' });
    if (r.some(m => m.body.toLowerCase() === text.toLowerCase() && now - m.at < 30e3)) return json(429, { error: 'repeat', message: 'You just said that.' });
  }
  const res = await env.DB.prepare('INSERT INTO chat_messages (at, account_id, username, role, body) VALUES (?, ?, ?, ?, ?)')
    .bind(now, a.id, a.username, a.role, text).run();
  // now and then, drop old chat
  if (Math.random() < 0.02) ctx.waitUntil(env.DB.prepare('DELETE FROM chat_messages WHERE at < ?').bind(now - KEEP_DAYS * 864e5).run());
  return json(200, { ok: true, message: msgOut({ id: res.meta.last_row_id, at: now, username: a.username, role: a.role, body: text }) });
}

async function del(request, env, mod) {
  const id = Number((await body(request)).id) | 0;
  const m = await env.DB.prepare('SELECT username, body FROM chat_messages WHERE id = ?').bind(id).first();
  if (!m) return json(404, { error: 'unknown', message: 'No such message.' });
  await env.DB.prepare('UPDATE chat_messages SET deleted_at = ?, deleted_by = ? WHERE id = ?').bind(Date.now(), mod.username, id).run();
  await log(env, mod.username, 'chat-delete', m.username, m.body);
  return json(200, { ok: true });
}

async function mute(request, env, mod) {
  const b = await body(request);
  const t = await byName(env, b.username);
  if (!t) return json(404, { error: 'unknown', message: 'No account with that name.' });
  const minutes = Number(b.minutes);
  if (minutes === 0) {
    await env.DB.prepare('DELETE FROM chat_mutes WHERE account_id = ?').bind(t.id).run();
    await log(env, mod.username, 'chat-unmute', t.username, '');
    return json(200, { ok: true, username: t.username, muted: false });
  }
  if (t.role === 'mod') return json(403, { error: 'mod', message: "Moderators can't be muted." });
  const until = minutes > 0 ? Date.now() + minutes * 60e3 : null;
  const reason = clean(b.reason, 200);
  await env.DB.prepare('INSERT INTO chat_mutes (account_id, until, reason, muted_by) VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET until = excluded.until, reason = excluded.reason, muted_by = excluded.muted_by')
    .bind(t.id, until, reason, mod.username).run();
  await log(env, mod.username, 'chat-mute', t.username, `${reason}${minutes > 0 ? ` (${minutes} min)` : ''}`);
  return json(200, { ok: true, username: t.username, muted: true, until });
}

async function announce(request, env, mod) {
  const b = await body(request);
  const title = clean(b.title, 120);
  if (!title) return json(400, { error: 'title', message: 'Give it a title.' });
  const text = String(b.body ?? '').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '').trim().slice(0, 2000);
  const at = Number(b.at) > 0 ? Number(b.at) : Date.now();
  const res = await env.DB.prepare('INSERT INTO announcements (at, author, title, body, link, pinned) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(at, mod.username, title, text, safeLink(b.link), b.pinned ? 1 : 0).run();
  await log(env, mod.username, 'announce', '', title);
  return json(200, { ok: true, id: res.meta.last_row_id });
}

async function unannounce(request, env, mod) {
  const id = Number((await body(request)).id) | 0;
  await env.DB.prepare('UPDATE announcements SET deleted_at = ? WHERE id = ?').bind(Date.now(), id).run();
  await log(env, mod.username, 'unannounce', '', String(id));
  return json(200, { ok: true });
}

export async function community(request, env, url, ctx) {
  const p = url.pathname;
  const m = request.method;
  if (p === '/api/community/feed' && m === 'GET') return feed(request, env, url);
  if (m !== 'POST') return json(405, { error: 'method' });
  const a = await authed(request, env);
  if (!a) return json(401, { error: 'signin', message: 'Sign in to your Vortal account first.' });
  if (p === '/api/community/chat') return post(request, env, ctx, a);
  if (a.role !== 'mod') return json(403, { error: 'mod', message: 'Moderators only.' });
  if (p === '/api/community/delete') return del(request, env, a);
  if (p === '/api/community/mute') return mute(request, env, a);
  if (p === '/api/community/announce') return announce(request, env, a);
  if (p === '/api/community/unannounce') return unannounce(request, env, a);
  return json(404, { error: 'unknown' });
}
