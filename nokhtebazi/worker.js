/* ═══════════════════════════════════════════════════════════════
   Nokhtebazi server on Cloudflare Workers.
   public/ is served as static assets; /api/* reaches this Worker, and
   each room is one Durable Object that owns its board. The server runs
   the same rules file as the browser (public/engine.js), so it decides
   every move: whose turn it is, which boxes close, and who wins.
   Players talk to their room over a WebSocket; idle rooms hibernate.
   ═══════════════════════════════════════════════════════════════ */
import { DurableObject } from 'cloudflare:workers';
import { SIZES, newGame, play, nextTurn } from './public/engine.js';

const ROOM_TTL = 1000 * 60 * 60 * 6;       // rooms close 6h after their last activity
const SAVE_EVERY = 1000 * 60 * 10;         // persist "last active" at most this often
const MAX_PLAYERS = 6;
const OPEN = 1;                            // WebSocket readyState
const COLORS = ['#A259FF', '#E05BC4', '#7B9BFF', '#FF6FAE', '#C9A7FF', '#8B7BFF', '#C77DDB'];
const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // no I/O/0/1

const pick = n => crypto.getRandomValues(new Uint32Array(1))[0] % n;
const newCode = () => Array.from({ length: 5 }, () => CODE_ALPHABET[pick(CODE_ALPHABET.length)]).join('');
const newToken = () => [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
const clean = (s, n = 16) => String(s == null ? '' : s).replace(/[\x00-\x1f<>]/g, '').trim().slice(0, n);
const roomOf = (env, code) => env.ROOMS.get(env.ROOMS.idFromName(code));

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

async function readJson(request, limit = 4096) {
  const text = await request.text();
  if (text.length > limit) throw new Error('too large');
  try { return JSON.parse(text || '{}') || {}; } catch { throw new Error('bad json'); }
}

/* ---------- Worker: routing ---------- */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
    try {
      const seg = url.pathname.split('/').filter(Boolean);   // ['api','rooms',code,action]
      if (seg[1] === 'health') return json(200, { ok: true });

      // POST /api/rooms -> open a room and take the first seat
      if (seg[1] === 'rooms' && seg.length === 2 && request.method === 'POST') {
        const body = await readJson(request);
        for (let attempt = 0; attempt < 6; attempt++) {
          const code = newCode();
          const made = await roomOf(env, code).create(code, body);
          if (made) return json(200, made);
        }
        return json(503, { error: 'busy' });
      }

      // /api/rooms/:code/... belongs to that room
      if (seg[1] === 'rooms' && seg[2]) {
        const code = seg[2].toUpperCase();
        if (!/^[A-Z0-9]{4,8}$/.test(code)) return json(404, { error: 'notfound' });
        return roomOf(env, code).fetch(request);
      }
      return json(404, { error: 'unknown' });
    } catch {
      return json(400, { error: 'bad' });
    }
  },
};

/* ═══════════ Room: one table ═══════════ */
export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    /** { code, size, phase: 'lobby'|'playing'|'over', host, seats: [{ name, color, token, left }], game, starter, touched } */
    this.room = null;
    this.lastSaved = 0;
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
    ctx.blockConcurrencyWhile(async () => {
      this.room = (await ctx.storage.get('room')) || null;
    });
  }

  /* ---------- persistence ---------- */
  async save() {
    this.room.touched = this.lastSaved = Date.now();
    await this.ctx.storage.put('room', this.room);
  }
  touch() {
    const now = Date.now();
    this.room.touched = now;
    if (now - this.lastSaved > SAVE_EVERY) {
      this.lastSaved = now;
      this.ctx.storage.put('room', this.room);
    }
  }

  /* ---------- connections ---------- */
  sockets(gone) {
    return this.ctx.getWebSockets().filter(ws => ws !== gone && ws.readyState === OPEN);
  }
  seatOf(ws) {
    const a = ws.deserializeAttachment();
    return a && Number.isInteger(a.seat) ? a.seat : -1;
  }
  onlineSeats(gone) {
    return new Set(this.sockets(gone).map(ws => this.seatOf(ws)).filter(s => s >= 0));
  }
  view(gone) {
    const r = this.room, online = this.onlineSeats(gone);
    return {
      code: r.code, size: r.size, phase: r.phase, host: r.host,
      seats: r.seats.map((s, i) => ({ name: s.name, color: s.color, online: online.has(i), left: !!s.left })),
      watching: this.sockets(gone).filter(ws => this.seatOf(ws) < 0).length,
      game: r.game,
    };
  }
  send(ws, msg) {
    try { ws.send(JSON.stringify(msg)); } catch { /* closing */ }
  }
  // Everyone gets the whole room plus their own seat number.
  pushRoom(skip, gone) {
    const room = JSON.stringify(this.view(gone));
    for (const ws of this.sockets(gone)) {
      if (ws === skip) continue;
      try { ws.send(`{"t":"room","you":${this.seatOf(ws)},"room":${room}}`); } catch { /* closing */ }
    }
  }
  // The host leads; if the host is away or gone, anyone seated can.
  canLead(seat) {
    const r = this.room;
    if (seat < 0 || r.seats[seat].left) return false;
    return seat === r.host || r.seats[r.host].left || !this.onlineSeats().has(r.host);
  }
  // If the player to move is away, pass the turn to someone who is here.
  keepTurnMoving(gone) {
    const r = this.room;
    if (r.phase !== 'playing') return false;
    const on = this.onlineSeats(gone);
    if (on.has(r.game.turn) || !on.size) return false;
    r.game.turn = nextTurn(r.game, r.game.turn, p => on.has(p));
    return true;
  }
  makeSeat(body, seats) {
    const taken = new Set(seats.filter(s => !s.left).map(s => s.color));
    const color = COLORS.includes(body.color) && !taken.has(body.color) ? body.color : (COLORS.find(c => !taken.has(c)) || COLORS[0]);
    return { name: clean(body.name) || `Player ${seats.length + 1}`, color, token: newToken(), left: false };
  }
  // Drop seats that left before a new game, renumbering everyone still here.
  compactSeats() {
    const r = this.room;
    if (!r.seats.some(s => s.left)) return;
    const map = new Map(), kept = [];
    r.seats.forEach((s, i) => { if (!s.left) { map.set(i, kept.length); kept.push(s); } });
    r.seats = kept;
    r.host = map.has(r.host) ? map.get(r.host) : 0;
    r.starter = 0;
    for (const ws of this.ctx.getWebSockets()) {
      const seat = this.seatOf(ws);
      if (seat >= 0) ws.serializeAttachment({ seat: map.has(seat) ? map.get(seat) : -1 });
    }
  }

  /* ---------- called by the Worker ---------- */
  async create(code, body) {
    if (this.room) return null;                  // that code is taken
    const seat = this.makeSeat(body, []);
    this.room = {
      code, size: SIZES[body.size] ? body.size : 'classic', phase: 'lobby', host: 0,
      seats: [seat], game: null, starter: 0, touched: Date.now(),
    };
    await this.save();
    await this.ctx.storage.setAlarm(Date.now() + ROOM_TTL);
    return { code, seat: 0, token: seat.token };
  }

  async fetch(request) {
    const r = this.room;
    if (!r) return json(404, { error: 'notfound' });
    const url = new URL(request.url);
    const action = url.pathname.split('/').filter(Boolean)[3];

    // POST /api/rooms/:code/join -> a seat, your old seat back, or a spectator's view
    if (action === 'join' && request.method === 'POST') {
      const body = await readJson(request).catch(() => ({}));
      const back = body.token ? r.seats.findIndex(s => s.token === body.token && !s.left) : -1;
      if (back >= 0) return json(200, { code: r.code, seat: back, token: body.token });
      if (r.phase !== 'lobby') return json(200, { code: r.code, seat: -1, token: null });
      if (r.seats.filter(s => !s.left).length >= MAX_PLAYERS) return json(409, { error: 'full' });
      const seat = this.makeSeat(body, r.seats);
      r.seats.push(seat);
      await this.save();
      this.pushRoom();
      return json(200, { code: r.code, seat: r.seats.length - 1, token: seat.token });
    }

    // GET /api/rooms/:code/socket?token= -> the live connection
    if (action === 'socket') {
      if ((request.headers.get('Upgrade') || '').toLowerCase() !== 'websocket') return json(426, { error: 'upgrade' });
      const token = url.searchParams.get('token');
      const seat = token ? r.seats.findIndex(s => s.token === token && !s.left) : -1;
      if (token && seat < 0) return json(403, { error: 'notmember' });
      const [client, server] = Object.values(new WebSocketPair());
      this.ctx.acceptWebSocket(server);
      server.serializeAttachment({ seat });
      this.touch();
      if (this.keepTurnMoving()) await this.save();
      this.send(server, { t: 'room', you: seat, room: this.view() });
      this.pushRoom(server);
      return new Response(null, { status: 101, webSocket: client });
    }

    if (!action && request.method === 'GET') return json(200, { code: r.code, phase: r.phase });
    return json(404, { error: 'unknown' });
  }

  async webSocketMessage(ws, raw) {
    const r = this.room;
    if (!r || typeof raw !== 'string' || raw.length > 1000) return;
    let m;
    try { m = JSON.parse(raw); } catch { return; }
    const seat = this.seatOf(ws);

    switch (m.t) {
      case 'cursor': {                           // relayed live, never stored
        if (seat < 0 || r.phase !== 'playing' || !Number.isFinite(m.x) || !Number.isFinite(m.y)) return;
        const text = JSON.stringify({ t: 'cursor', seat, x: Math.round(m.x), y: Math.round(m.y) });
        for (const other of this.sockets()) if (other !== ws) { try { other.send(text); } catch { /* closing */ } }
        return;
      }
      case 'move': {
        if (r.phase !== 'playing' || seat < 0) return this.send(ws, { t: 'error', error: 'turn' });
        const on = this.onlineSeats();
        // skip players who are away, but never hand the turn straight back to the mover
        const res = play(r.game, seat, m.kind, m.i, p => on.has(p) && p !== seat);
        if (!res.ok) return this.send(ws, { t: 'error', error: res.error });
        if (r.game.over) r.phase = 'over';
        await this.save();
        this.pushRoom();
        return;
      }
      case 'size': {
        if (r.phase !== 'lobby' || !this.canLead(seat) || !SIZES[m.size]) return;
        r.size = m.size;
        await this.save();
        this.pushRoom();
        return;
      }
      case 'start': {
        if (r.phase === 'playing' || !this.canLead(seat)) return;
        this.compactSeats();
        if (r.seats.length < 2) return this.send(ws, { t: 'error', error: 'needtwo' });
        if (SIZES[m.size]) r.size = m.size;
        r.game = newGame(r.size, r.seats.length, r.starter);
        r.starter = (r.starter + 1) % r.seats.length;
        r.phase = 'playing';
        this.keepTurnMoving();
        await this.save();
        this.pushRoom();
        return;
      }
      case 'lobby': {                            // back to the room after a game, so others can join
        if (r.phase !== 'over' || !this.canLead(seat)) return;
        r.phase = 'lobby';
        r.game = null;
        await this.save();
        this.pushRoom();
        return;
      }
      case 'leave': {
        if (seat < 0) return;
        r.seats[seat].left = true;
        if (r.host === seat) {
          const next = r.seats.findIndex(s => !s.left);
          r.host = next >= 0 ? next : 0;
        }
        ws.serializeAttachment({ seat: -1 });
        if (r.phase === 'playing' && r.game.turn === seat) {
          const on = this.onlineSeats();
          r.game.turn = nextTurn(r.game, seat, p => on.has(p) && !r.seats[p].left);
        }
        await this.save();
        this.pushRoom(ws);
        try { ws.close(1000, 'Left'); } catch { /* already closed */ }
        return;
      }
    }
  }

  async webSocketClose(ws, code, reason) {
    try { ws.close(code, reason); } catch { /* already closed */ }
    await this.dropped(ws);
  }
  async webSocketError(ws) {
    await this.dropped(ws);
  }
  async dropped(ws) {
    if (!this.room) return;
    if (this.keepTurnMoving(ws)) await this.save();
    this.pushRoom(ws, ws);
  }

  // Rooms close 6 hours after their last activity.
  async alarm() {
    const r = this.room;
    if (!r) return;
    const due = r.touched + ROOM_TTL;
    if (Date.now() < due) { await this.ctx.storage.setAlarm(due); return; }
    this.room = null;
    for (const ws of this.ctx.getWebSockets()) { try { ws.close(1000, 'Room closed'); } catch { /* gone */ } }
    await this.ctx.storage.deleteAll();
  }
}
