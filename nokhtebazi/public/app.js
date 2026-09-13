/* ═══════════════════════════════════════════════════════════════
   Nokhtebazi client: the home screen, online rooms, and the board.
   The rules live in engine.js, which the server runs too.
   ═══════════════════════════════════════════════════════════════ */
import { SIZES, LEVELS, newGame, play, botMove, winners, isFree } from './engine.js';

const COLORS = ['#A259FF', '#E05BC4', '#7B9BFF', '#FF6FAE', '#C9A7FF', '#8B7BFF', '#C77DDB'];
const COLOR_NAMES = ['Violet', 'Orchid', 'Periwinkle', 'Rose', 'Lavender', 'Iris', 'Plum'];
const GAP = 60;                                  // board units between neighbouring dots
const FREE_LINE = '#1D1631';
const DOT = '#8C80A8';
const BOARD_FONT = '"Chakra Petch", "Vazirmatn", sans-serif';
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const rgba = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;
const initial = name => ([...String(name).trim()][0] || '?').toUpperCase();
const store = {
  get: k => { try { return localStorage.getItem('nokhte.' + k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem('nokhte.' + k, v); } catch { /* storage blocked */ } },
  del: k => { try { localStorage.removeItem('nokhte.' + k); } catch { /* storage blocked */ } },
};

/* ══════════ words ══════════ */
const WORDS = {
  en: {
    title: 'Nokhtebazi', subtitle: 'نقطه بازی · the dots game', byVortal: 'A Vortal game',
    tagline: 'Draw a line. Close a box. Go again.',
    how: 'Take turns joining two dots. Draw the fourth side of a box to claim it and draw again. Most boxes wins.',
    yourName: 'Your name', colour: 'Colour', board: 'Board',
    quick: 'Quick', classic: 'Classic', big: 'Big', marathon: 'Marathon',
    online: 'Play online', create: 'Create a room', roomCode: 'Room code', join: 'Join',
    local: 'Play on this device', vsCpu: 'Computer', players: '{n} players', start: 'Start', resume: 'Resume your game',
    computer: 'Computer', playerN: 'Player {n}', computerLevel: 'Computer ({level})',
    difficulty: 'Difficulty', easy: 'Easy', normal: 'Normal', hard: 'Hard',
    room: 'Room', copyLink: 'Copy invite link', copied: 'Invite link copied', host: 'Host', you: 'You', here: 'Here', away: 'Away',
    needTwo: 'You need at least two players to start.', waitingHost: 'Waiting for the host to start…',
    watchingNote: 'A game is in progress, so you are watching.',
    leave: 'Leave', leaveConfirm: 'Leave this game? Your turns will be skipped.',
    yourTurn: 'Your turn', turnOf: "{name}'s turn", thinking: '{name} is thinking…', watching: 'Watching',
    gameOver: 'Game over', wins: '{name} wins', draw: "It's a draw", playAgain: 'Play again',
    backToRoom: 'Back to the room', home: 'Home', viewBoard: 'View the board', waitingRematch: 'Waiting for the host…',
    fit: 'Fit', zoomIn: 'Zoom in', zoomOut: 'Zoom out', boardLabel: 'Game board',
    reconnecting: 'Reconnecting…', closed: 'This room has closed.', nameFirst: 'Enter your name first.',
    joinPrompt: 'Enter your name, then press Join to enter room {code}.',
    err_notfound: 'No room with that code. Check the letters and try again.',
    err_full: 'That room is full (6 players).', err_turn: "It's not your turn.", err_taken: 'That line is already drawn.',
    err_over: 'The game is over.', err_needtwo: 'You need at least two players to start.',
    err_network: "Can't reach the server. Check your connection.", err_busy: 'The server is busy. Try again.',
    err_notmember: 'Your seat in that room has expired.', err_bad: 'Something went wrong. Try again.',
  },
  fa: {
    title: 'نقطه بازی', subtitle: 'Nokhtebazi · بازی نقطه‌ها', byVortal: 'بازی‌ای از ورتال',
    tagline: 'خط بکش. خانه را ببند. دوباره بازی کن.',
    how: 'به نوبت دو نقطه را به هم وصل کنید. هر کس ضلع چهارم یک خانه را بکشد، آن خانه مال اوست و دوباره بازی می‌کند. بیشترین خانه برنده است.',
    yourName: 'نام شما', colour: 'رنگ', board: 'صفحه',
    quick: 'سریع', classic: 'کلاسیک', big: 'بزرگ', marathon: 'ماراتن',
    online: 'بازی آنلاین', create: 'ساخت اتاق', roomCode: 'کد اتاق', join: 'ورود',
    local: 'بازی روی همین دستگاه', vsCpu: 'رایانه', players: '{n} نفر', start: 'شروع', resume: 'ادامهٔ بازی',
    computer: 'رایانه', playerN: 'بازیکن {n}', computerLevel: 'رایانه ({level})',
    difficulty: 'سطح', easy: 'آسان', normal: 'متوسط', hard: 'سخت',
    room: 'اتاق', copyLink: 'کپی لینک دعوت', copied: 'لینک دعوت کپی شد', host: 'میزبان', you: 'شما', here: 'حاضر', away: 'غایب',
    needTwo: 'برای شروع دست‌کم دو بازیکن لازم است.', waitingHost: 'منتظر شروع بازی توسط میزبان…',
    watchingNote: 'بازی در جریان است؛ شما تماشاگر هستید.',
    leave: 'خروج', leaveConfirm: 'از بازی خارج می‌شوید؟ نوبت‌های شما رد می‌شود.',
    yourTurn: 'نوبت شماست', turnOf: 'نوبت {name}', thinking: '{name} در حال فکر کردن…', watching: 'تماشا',
    gameOver: 'پایان بازی', wins: '{name} برنده شد', draw: 'مساوی شد', playAgain: 'دوباره',
    backToRoom: 'بازگشت به اتاق', home: 'خانه', viewBoard: 'دیدن صفحه', waitingRematch: 'منتظر میزبان…',
    fit: 'اندازه', zoomIn: 'بزرگ‌نمایی', zoomOut: 'کوچک‌نمایی', boardLabel: 'صفحهٔ بازی',
    reconnecting: 'در حال اتصال دوباره…', closed: 'این اتاق بسته شده است.', nameFirst: 'اول نام خود را وارد کنید.',
    joinPrompt: 'نام خود را وارد کنید و «ورود» را بزنید تا وارد اتاق {code} شوید.',
    err_notfound: 'اتاقی با این کد پیدا نشد. حروف را بررسی کنید.',
    err_full: 'این اتاق پر است (۶ نفر).', err_turn: 'نوبت شما نیست.', err_taken: 'این خط قبلاً کشیده شده.',
    err_over: 'بازی تمام شده است.', err_needtwo: 'برای شروع دست‌کم دو بازیکن لازم است.',
    err_network: 'اتصال به سرور ممکن نیست. اینترنت خود را بررسی کنید.', err_busy: 'سرور شلوغ است. دوباره تلاش کنید.',
    err_notmember: 'جای شما در آن اتاق منقضی شده است.', err_bad: 'مشکلی پیش آمد. دوباره تلاش کنید.',
  },
};
let lang = store.get('lang') || ((navigator.language || '').toLowerCase().startsWith('fa') ? 'fa' : 'en');
function t(key, vars = {}) {
  const s = WORDS[lang][key] ?? WORDS.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ''));
}
const errText = code => (WORDS.en['err_' + code] ? t('err_' + code) : t('err_bad'));

function applyLang() {
  const root = document.documentElement;
  root.lang = lang;
  root.dir = lang === 'fa' ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
  document.querySelectorAll('[data-i18n-label]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nLabel)); });
  const btn = $('#lang');
  btn.textContent = lang === 'fa' ? 'English' : 'فارسی';
  btn.lang = lang === 'fa' ? 'en' : 'fa';
  document.title = lang === 'fa' ? 'نقطه بازی' : 'Nokhtebazi';
  renderScreen();
}

/* ══════════ state ══════════ */
const S = {
  screen: 'home',
  mode: null,                       // 'online' | 'local'
  name: store.get('name') || '',
  color: COLORS.includes(store.get('color')) ? store.get('color') : COLORS[0],
  size: SIZES[store.get('size')] ? store.get('size') : 'classic',
  opponents: ['cpu', '2', '3', '4'].includes(store.get('opponents')) ? store.get('opponents') : 'cpu',
  level: LEVELS.includes(store.get('level')) ? store.get('level') : 'normal',
  // online
  code: null, token: null, you: -1, room: null, ws: null, leaving: false, failures: 0, pending: null,
  cursors: new Map(),
  // local
  local: null,
  // view
  fitFor: '', overHidden: false,
};
const game = () => (S.mode === 'online' ? S.room && S.room.game : S.local && S.local.game);
const players = () => (S.mode === 'online' ? (S.room ? S.room.seats : []) : (S.local ? S.local.players : []));
function myTurn() {
  const g = game();
  if (!g || g.over) return false;
  if (S.mode === 'online') return g.turn === S.you;
  return !players()[g.turn]?.cpu;
}
function myColor() {
  const ps = players(), g = game();
  if (S.mode === 'online') return ps[S.you]?.color || S.color;
  return (g && ps[g.turn]?.color) || S.color;
}

function show(screen) {
  S.screen = screen;
  for (const id of ['home', 'lobby', 'game']) $('#' + id).hidden = id !== screen;
  document.body.dataset.screen = screen;
  if (screen === 'home') demo.run(); else demo.stop();
  if (screen === 'game') sizeCanvas();
  renderScreen();
}
function renderScreen() {
  if (S.screen === 'home') renderHome();
  else if (S.screen === 'lobby') renderLobby();
  else renderGame();
}

let toastTimer = 0;
function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2800);
}
function status(msg) { const el = $('#status'); el.textContent = msg; el.hidden = !msg; }
function homeError(msg) { const el = $('#homeError'); el.textContent = msg || ''; el.hidden = !msg; }

/* ══════════ home ══════════ */
function choice(el, options, value, onPick, disabled = false) {
  el.innerHTML = options.map(([v, label, sub]) =>
    `<button type="button" data-v="${v}" aria-pressed="${v === value}"${disabled ? ' disabled' : ''}><span>${esc(label)}</span>${sub ? `<small>${esc(sub)}</small>` : ''}</button>`).join('');
  el.onclick = e => {
    const b = e.target.closest('button[data-v]');
    if (b && !b.disabled && b.dataset.v !== value) onPick(b.dataset.v);
  };
}
const sizeOptions = () => Object.entries(SIZES).map(([k, s]) => [k, t(k), `${s.cols}×${s.rows}`]);

function renderHome() {
  const name = $('#name');
  if (document.activeElement !== name) name.value = S.name;
  $('#swatches').innerHTML = COLORS.map((c, i) =>
    `<button type="button" class="swatch" data-c="${c}" style="--c:${c}" aria-pressed="${c === S.color}" aria-label="${COLOR_NAMES[i]}"></button>`).join('');
  choice($('#sizes'), sizeOptions(), S.size, v => { S.size = v; store.set('size', v); renderHome(); });
  choice($('#opponents'), [['cpu', t('vsCpu')], ...[2, 3, 4].map(n => [String(n), t('players', { n })])], S.opponents,
    v => { S.opponents = v; store.set('opponents', v); renderHome(); });
  $('#levelField').hidden = S.opponents !== 'cpu';
  choice($('#levels'), LEVELS.map(l => [l, t(l)]), S.level, v => { S.level = v; store.set('level', v); renderHome(); });
  $('#resume').hidden = !loadLocal();
}

function requireName() {
  if (S.name.trim()) return true;
  homeError(t('nameFirst'));
  $('#name').focus();
  return false;
}

/* ══════════ online ══════════ */
async function api(path, body) {
  let res;
  try {
    res = await fetch('/api/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  } catch {
    throw new Error('network');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'network');
  return data;
}

async function createRoom() {
  if (!requireName()) return;
  homeError('');
  try { enterRoom(await api('rooms', { name: S.name, color: S.color, size: S.size })); }
  catch (e) { homeError(errText(e.message)); }
}

async function joinRoom(raw) {
  const code = String(raw || '').trim().toUpperCase();
  if (!code) { $('#code').focus(); return; }
  if (!requireName()) return;
  homeError('');
  try {
    enterRoom(await api(`rooms/${encodeURIComponent(code)}/join`, { name: S.name, color: S.color, token: store.get('seat.' + code) }));
  } catch (e) {
    homeError(errText(e.message));
  }
}

function enterRoom(r) {
  Object.assign(S, { mode: 'online', code: r.code, token: r.token, you: r.seat, leaving: false, failures: 0, overHidden: false, room: null });
  if (r.token) store.set('seat.' + r.code, r.token);
  history.replaceState(null, '', `?room=${r.code}`);
  connect();
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/rooms/${S.code}/socket${S.token ? `?token=${S.token}` : ''}`);
  S.ws = ws;
  let opened = false, ping = 0;
  ws.onopen = () => {
    opened = true;
    S.failures = 0;
    status('');
    ping = setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 30000);
  };
  ws.onmessage = e => {
    if (e.data === 'pong') return;
    let m;
    try { m = JSON.parse(e.data); } catch { return; }
    onMessage(m);
  };
  ws.onclose = ev => {
    clearInterval(ping);
    if (S.ws !== ws || S.leaving) return;
    if (ev.reason === 'Room closed') { toast(t('closed')); goHome(); return; }
    if (!opened && ++S.failures >= 4) {
      store.del('seat.' + S.code);
      toast(errText(S.token ? 'notmember' : 'network'));
      goHome();
      return;
    }
    status(t('reconnecting'));
    setTimeout(() => { if (S.ws === ws && !S.leaving) connect(); }, opened ? 1500 : 2500);
  };
}

function send(msg) {
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(msg));
}

function onMessage(m) {
  if (m.t === 'room') {
    const before = S.room && S.room.phase;
    S.you = m.you;
    S.room = m.room;
    S.pending = null;
    if (m.room.phase === 'playing' && before !== 'playing') S.overHidden = false;
    if (m.room.phase === 'lobby') { if (S.screen !== 'lobby') show('lobby'); else renderLobby(); }
    else if (S.screen !== 'game') show('game');
    else renderGame();
  } else if (m.t === 'cursor') {
    S.cursors.set(m.seat, { x: m.x, y: m.y, at: performance.now() });
    requestDraw();
  } else if (m.t === 'error') {
    S.pending = null;
    if (m.error !== 'taken') toast(errText(m.error));
    requestDraw();
  }
}

function leaveRoom() {
  if (S.mode === 'online') {
    send({ t: 'leave' });
    store.del('seat.' + S.code);
  }
  goHome();
}

function goHome() {
  S.leaving = true;
  const ws = S.ws;
  S.ws = null;
  if (ws) setTimeout(() => { try { ws.close(); } catch { /* already closed */ } }, 120);
  clearTimeout(botTimer);
  Object.assign(S, { mode: null, room: null, code: null, token: null, you: -1, pending: null, fitFor: '' });
  S.cursors.clear();
  history.replaceState(null, '', location.pathname);
  status('');
  $('#over').hidden = true;
  show('home');
}

/* ══════════ lobby ══════════ */
function canLead() {
  const r = S.room;
  if (!r || S.you < 0 || !r.seats[S.you] || r.seats[S.you].left) return false;
  const host = r.seats[r.host];
  return S.you === r.host || !host || host.left || !host.online;
}

function renderLobby() {
  const r = S.room;
  if (!r) return;
  $('#roomCode').textContent = r.code;
  $('#lobbyPlayers').innerHTML = r.seats.map((s, i) => s.left ? '' : `
    <li style="--c:${s.color}">
      <i class="dot"></i><span class="pname">${esc(s.name)}</span>
      ${i === r.host ? `<span class="badge">${esc(t('host'))}</span>` : ''}
      ${i === S.you ? `<span class="badge">${esc(t('you'))}</span>` : ''}
      <span class="presence${s.online ? ' is-on' : ''}">${esc(s.online ? t('here') : t('away'))}</span>
    </li>`).join('');
  const lead = canLead();
  const count = r.seats.filter(s => !s.left).length;
  choice($('#lobbySizes'), sizeOptions(), r.size, v => send({ t: 'size', size: v }), !lead);
  $('#startOnline').hidden = !lead;
  $('#startOnline').disabled = count < 2;
  $('#lobbyNote').textContent = S.you < 0 ? t('watchingNote') : !lead ? t('waitingHost') : count < 2 ? t('needTwo') : '';
}

/* ══════════ game HUD ══════════ */
function turnText(g, ps) {
  const p = ps[g.turn];
  if (!p) return '';
  if (S.mode === 'online') return g.turn === S.you ? t('yourTurn') : t('turnOf', { name: p.name });
  if (p.cpu) return t('thinking', { name: p.name });
  return ps.filter(q => !q.cpu).length > 1 ? t('turnOf', { name: p.name }) : t('yourTurn');
}

function renderGame() {
  const g = game();
  if (!g) return;
  const ps = players();
  noteChanges(g);
  const now = performance.now();
  const turnChanged = fx.turn !== g.turn;
  fx.turn = g.turn;
  const code = $('#hudCode');
  code.hidden = S.mode !== 'online';
  if (S.mode === 'online') code.textContent = S.you < 0 ? `${S.room.code} · ${t('watching')}` : S.room.code;

  $('#scores').innerHTML = ps.map((p, i) => `
    <li class="${!g.over && i === g.turn ? 'is-turn' : ''}${p.online === false || p.left ? ' is-away' : ''}${now - (fx.bumped.get(i) || -1e9) < 150 ? ' bump' : ''}" style="--c:${p.color}">
      <i class="dot"></i><span class="pname">${esc(p.name)}${S.mode === 'online' && i === S.you ? ` (${esc(t('you'))})` : ''}</span><b>${g.scores[i]}</b>
    </li>`).join('');

  const turn = $('#turn');
  if (g.over) turn.innerHTML = S.overHidden ? `<button type="button" id="showOver">${esc(t('gameOver'))}</button>` : '';
  else turn.innerHTML = `<span${turnChanged ? ' class="is-new"' : ''} style="--c:${ps[g.turn] ? ps[g.turn].color : 'transparent'}">${esc(turnText(g, ps))}</span>`;

  if (S.fitFor !== `${g.cols}x${g.rows}`) fit();
  if (g.over && !S.overHidden) showOver(); else $('#over').hidden = true;
  requestDraw();
}

function showOver() {
  const g = game(), ps = players(), w = winners(g);
  $('#overTitle').textContent = w.length === 1 ? t('wins', { name: ps[w[0]].name }) : t('draw');
  $('#overScores').innerHTML = ps.map((p, i) => [p, g.scores[i]]).sort((a, b) => b[1] - a[1])
    .map(([p, s]) => `<li style="--c:${p.color}"><i class="dot"></i><span class="pname">${esc(p.name)}</span><b>${s}</b></li>`).join('');
  let actions;
  if (S.mode === 'local') actions = [['again', t('playAgain'), 'solid'], ['home', t('home'), 'line']];
  else if (canLead()) actions = [['again', t('playAgain'), 'solid'], ['room', t('backToRoom'), 'line'], ['leave', t('leave'), 'quiet']];
  else actions = [['leave', t('leave'), 'line']];
  actions.push(['view', t('viewBoard'), 'quiet']);
  $('#overActions').innerHTML = actions.map(([a, label, kind]) =>
    `<button type="button" class="btn btn--${kind}" data-act="${a}">${esc(label)}</button>`).join('') +
    (S.mode === 'online' && !canLead() ? `<p class="note">${esc(t('waitingRematch'))}</p>` : '');
  $('#over').hidden = false;
}

/* ══════════ local play ══════════ */
function loadLocal() {
  try {
    const l = JSON.parse(store.get('local'));
    return l && l.game && Array.isArray(l.players) && !l.game.over ? l : null;
  } catch {
    return null;
  }
}
function saveLocal() {
  if (S.local && !S.local.game.over) store.set('local', JSON.stringify(S.local));
  else store.del('local');
}

function startLocal() {
  const others = COLORS.filter(c => c !== S.color);
  const list = [{ name: S.name.trim() || t('you'), color: S.color }];
  if (S.opponents === 'cpu') list.push({ name: t('computerLevel', { level: t(S.level) }), color: others[0], cpu: true, level: S.level });
  else for (let i = 1; i < Number(S.opponents); i++) list.push({ name: t('playerN', { n: i + 1 }), color: others[i - 1] });
  beginLocal({ players: list, game: newGame(S.size, list.length, 0), starter: 0 });
}
function restartLocal() {
  const l = S.local;
  const starter = (l.starter + 1) % l.players.length;
  beginLocal({ players: l.players, game: newGame(l.game.size, l.players.length, starter), starter });
}
function beginLocal(local) {
  Object.assign(S, { local, mode: 'local', overHidden: false, fitFor: '' });
  saveLocal();
  show('game');
  maybeBot();
}

let botTimer = 0;
function maybeBot() {
  clearTimeout(botTimer);
  const g = S.local && S.local.game;
  if (S.mode !== 'local' || !g || g.over || !S.local.players[g.turn].cpu) return;
  botTimer = setTimeout(() => {
    if (S.mode !== 'local' || S.screen !== 'game') return;
    const [kind, i] = botMove(g, Math.random, S.local.players[g.turn].level || 'hard');
    play(g, g.turn, kind, i);
    saveLocal();
    renderGame();
    maybeBot();
  }, reduceMotion ? 250 : 520);
}

function move(kind, i) {
  if (S.mode === 'local') {
    const g = S.local.game;
    if (!play(g, g.turn, kind, i).ok) return;
    saveLocal();
    renderGame();
    maybeBot();
  } else if (!S.pending) {
    S.pending = [kind, i];
    send({ t: 'move', kind, i });
    requestDraw();
  }
}

/* ══════════ the board ══════════ */
const canvas = $('#board');
const ctx = canvas.getContext('2d');
const cam = { x: 0, y: 0, z: 1 };
let hover = null, drawQueued = false, fadeTimer = 0;

function sizeCanvas() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(innerWidth * dpr);
  canvas.height = Math.round(innerHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  requestDraw();
}

function fit() {
  const g = game();
  if (!g) return;
  const top = Math.max(110, $('#scores').getBoundingClientRect().bottom + 18);
  const bottom = 78, side = 24;
  const w = g.cols * GAP, h = g.rows * GAP;
  const availW = innerWidth - side * 2, availH = innerHeight - top - bottom;
  cam.z = clamp(Math.min(availW / w, availH / h), 0.12, 2.2);
  cam.x = (innerWidth - w * cam.z) / 2;
  cam.y = top + (availH - h * cam.z) / 2;
  S.fitFor = `${g.cols}x${g.rows}`;
  requestDraw();
}

function zoomAt(sx, sy, factor) {
  const z = clamp(cam.z * factor, 0.12, 3);
  const bx = (sx - cam.x) / cam.z, by = (sy - cam.y) / cam.z;
  cam.z = z;
  cam.x = sx - bx * z;
  cam.y = sy - by * z;
  requestDraw();
}

function requestDraw() {
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(draw);
}

function lineEnds(g, kind, i) {
  if (kind === 'h') {
    const x = i % g.cols, y = (i / g.cols) | 0;
    return [x * GAP, y * GAP, (x + 1) * GAP, y * GAP];
  }
  const W = g.cols + 1, x = i % W, y = (i / W) | 0;
  return [x * GAP, y * GAP, x * GAP, (y + 1) * GAP];
}
function linePath(c, g, kind, i, upTo = 1) {
  const [x1, y1, x2, y2] = lineEnds(g, kind, i);
  c.moveTo(x1, y1);
  c.lineTo(x1 + (x2 - x1) * upTo, y1 + (y2 - y1) * upTo);
}

/* Motion: the newest line draws itself, fresh boxes fill in, scores bump. */
const LINE_MS = 200, BOX_MS = 380;
const easeOut = p => 1 - Math.pow(1 - Math.min(1, Math.max(0, p)), 3);
const fx = { line: null, boxes: new Map(), bumped: new Map(), seen: null, turn: -1 };
function noteChanges(g) {
  const prev = fx.seen;
  fx.seen = { moves: g.moves, boxes: g.boxes.slice(), scores: g.scores.slice() };
  if (reduceMotion || !prev || prev.boxes.length !== g.boxes.length || g.moves !== prev.moves + 1) return;
  const now = performance.now();
  if (g.last) fx.line = { kind: g.last.kind, i: g.last.i, at: now };
  g.boxes.forEach((o, b) => { if (o >= 0 && prev.boxes[b] < 0) fx.boxes.set(b, now + LINE_MS * 0.6); });
  g.scores.forEach((s, p) => { if (s > prev.scores[p]) fx.bumped.set(p, now); });
}

// Draws a whole game in board units; the caller sets up the transform.
function paintBoard(c, g, colors, o = {}) {
  for (let b = 0; b < g.boxes.length; b++) {
    const owner = g.boxes[b];
    if (owner < 0) continue;
    const x = (b % g.cols) * GAP, y = ((b / g.cols) | 0) * GAP;
    const grow = o.fx && o.fx.boxes.has(b) ? easeOut(o.fx.boxes.get(b)) : 1;
    const inset = 6 + (1 - grow) * GAP * 0.3;
    c.fillStyle = rgba(colors[owner], 0.24 * grow + (1 - grow) * 0.5 * (grow > 0 ? 1 : 0));
    c.fillRect(x + inset, y + inset, GAP - inset * 2, GAP - inset * 2);
    if (o.letters && grow > 0.3) {
      c.fillStyle = rgba(colors[owner], 0.95 * grow);
      c.font = `700 ${GAP * 0.4}px ${BOARD_FONT}`;
      c.textAlign = 'center';
      c.textBaseline = 'middle';
      c.fillText(o.letters[owner], x + GAP / 2, y + GAP / 2 + 1);
    }
  }
  c.lineCap = 'round';
  c.lineWidth = 6;
  c.strokeStyle = FREE_LINE;
  c.beginPath();
  g.h.forEach((p, i) => { if (p < 0) linePath(c, g, 'h', i); });
  g.v.forEach((p, i) => { if (p < 0) linePath(c, g, 'v', i); });
  c.stroke();

  if (o.preview) {
    c.strokeStyle = rgba(o.preview.color, o.preview.alpha);
    c.beginPath(); linePath(c, g, o.preview.kind, o.preview.i); c.stroke();
  }
  const drawing = o.fx && o.fx.line;          // the newest line, still growing
  const isDrawing = (kind, i) => drawing && drawing.kind === kind && drawing.i === i;
  colors.forEach((color, p) => {
    c.beginPath();
    let any = false;
    g.h.forEach((q, i) => { if (q === p && !isDrawing('h', i)) { linePath(c, g, 'h', i); any = true; } });
    g.v.forEach((q, i) => { if (q === p && !isDrawing('v', i)) { linePath(c, g, 'v', i); any = true; } });
    if (!any) return;
    c.strokeStyle = color;
    c.shadowColor = color;
    c.shadowBlur = o.glow ?? 10;
    c.stroke();
  });
  if (drawing) {
    const owner = (drawing.kind === 'h' ? g.h : g.v)[drawing.i];
    const color = colors[owner] || '#FFFFFF';
    c.strokeStyle = color;
    c.shadowColor = color;
    c.shadowBlur = 18;
    c.beginPath(); linePath(c, g, drawing.kind, drawing.i, easeOut(drawing.p)); c.stroke();
  }
  c.shadowBlur = 0;

  if (g.last && !drawing) {
    c.strokeStyle = 'rgba(255,255,255,.85)';
    c.lineWidth = 2;
    c.beginPath(); linePath(c, g, g.last.kind, g.last.i); c.stroke();
  }
  c.fillStyle = DOT;
  c.beginPath();
  for (let y = 0; y <= g.rows; y++) {
    for (let x = 0; x <= g.cols; x++) { c.moveTo(x * GAP + 4.5, y * GAP); c.arc(x * GAP, y * GAP, 4.5, 0, Math.PI * 2); }
  }
  c.fill();
}

function draw() {
  drawQueued = false;
  ctx.clearRect(0, 0, innerWidth, innerHeight);
  const g = game();
  if (!g || S.screen !== 'game') return;
  const ps = players();
  let preview = null;
  if (S.pending) preview = { kind: S.pending[0], i: S.pending[1], color: myColor(), alpha: 0.9 };
  else if (hover && myTurn() && isFree(g, hover[0], hover[1])) preview = { kind: hover[0], i: hover[1], color: myColor(), alpha: 0.5 };

  // Work out how far along each animation is; keep drawing frames until they finish.
  const now = performance.now();
  const motion = { line: null, boxes: new Map() };
  if (fx.line) {
    const p = (now - fx.line.at) / LINE_MS;
    if (p < 1) motion.line = { ...fx.line, p }; else fx.line = null;
  }
  for (const [b, at] of fx.boxes) {
    const p = (now - at) / BOX_MS;
    if (p < 1) motion.boxes.set(b, Math.max(0, p)); else fx.boxes.delete(b);
  }

  ctx.save();
  ctx.translate(cam.x, cam.y);
  ctx.scale(cam.z, cam.z);
  paintBoard(ctx, g, ps.map(p => p.color), { preview, fx: motion, letters: cam.z * GAP >= 26 ? ps.map(p => initial(p.name)) : null });
  ctx.restore();
  drawCursors(ps);
  if (motion.line || motion.boxes.size) requestDraw();
}

// Other players' pointers, with their names, fading out when they stop moving.
function drawCursors(ps) {
  const now = performance.now();
  let alive = false;
  ctx.font = `600 12px ${BOARD_FONT}`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const [seat, c] of S.cursors) {
    const p = ps[seat];
    const age = now - c.at;
    if (!p || seat === S.you || age > 5000) continue;
    alive = true;
    const sx = cam.x + c.x * cam.z, sy = cam.y + c.y * cam.z;
    ctx.globalAlpha = age < 3500 ? 1 : 1 - (age - 3500) / 1500;
    ctx.fillStyle = p.color;
    ctx.beginPath(); ctx.arc(sx, sy, 6, 0, Math.PI * 2); ctx.fill();
    const w = ctx.measureText(p.name).width + 14;
    ctx.fillStyle = 'rgba(10,7,17,.85)';
    ctx.fillRect(sx + 10, sy - 27, w, 20);
    ctx.fillStyle = p.color;
    ctx.fillText(p.name, sx + 17, sy - 17);
  }
  ctx.globalAlpha = 1;
  if (alive && !fadeTimer) fadeTimer = setTimeout(() => { fadeTimer = 0; requestDraw(); }, 200);
}

// The line nearest a screen point, if the point is close enough to one.
function lineAt(sx, sy) {
  const g = game();
  if (!g) return null;
  const gx = (sx - cam.x) / cam.z / GAP, gy = (sy - cam.y) / cam.z / GAP;
  let best = null, reach = Math.min(0.5, Math.max(0.3, 18 / (GAP * cam.z)));
  const hy = Math.round(gy), hx = Math.floor(gx);
  if (hx >= 0 && hx < g.cols && hy >= 0 && hy <= g.rows && Math.abs(gy - hy) < reach) { reach = Math.abs(gy - hy); best = ['h', hy * g.cols + hx]; }
  const vx = Math.round(gx), vy = Math.floor(gy);
  if (vx >= 0 && vx <= g.cols && vy >= 0 && vy < g.rows && Math.abs(gx - vx) < reach) best = ['v', vy * (g.cols + 1) + vx];
  return best;
}

function tapAt(sx, sy) {
  const line = lineAt(sx, sy);
  const g = game();
  if (!line || !g || g.over || !isFree(g, line[0], line[1])) return;
  if (!myTurn()) {
    if (S.mode === 'online' && S.you >= 0) toast(t('err_turn'));
    return;
  }
  move(line[0], line[1]);
}

let lastCursor = 0;
function sendCursor(sx, sy) {
  if (S.mode !== 'online' || S.you < 0 || !S.room || S.room.phase !== 'playing') return;
  const now = performance.now();
  if (now - lastCursor < 90) return;
  lastCursor = now;
  send({ t: 'cursor', x: (sx - cam.x) / cam.z, y: (sy - cam.y) / cam.z });
}

// Drag to pan, pinch or wheel to zoom, tap to draw.
const pointers = new Map();
let gesture = null;
const spread = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

canvas.addEventListener('pointerdown', e => {
  try { canvas.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 1) {
    gesture = { kind: 'pan', sx: e.clientX, sy: e.clientY, cx: cam.x, cy: cam.y, moved: false };
  } else if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    gesture = { kind: 'pinch', d: spread(a, b) || 1, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, z: cam.z, cx: cam.x, cy: cam.y };
  }
});
canvas.addEventListener('pointermove', e => {
  if (e.pointerType === 'mouse' && !pointers.size) {
    const line = lineAt(e.clientX, e.clientY);
    if (String(line) !== String(hover)) { hover = line; requestDraw(); }
    const g = game();
    canvas.style.cursor = line && myTurn() && isFree(g, line[0], line[1]) ? 'pointer' : '';
  }
  sendCursor(e.clientX, e.clientY);
  if (!pointers.has(e.pointerId)) return;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (gesture && gesture.kind === 'pan') {
    const dx = e.clientX - gesture.sx, dy = e.clientY - gesture.sy;
    if (!gesture.moved && Math.hypot(dx, dy) > 7) gesture.moved = true;
    if (gesture.moved) { cam.x = gesture.cx + dx; cam.y = gesture.cy + dy; requestDraw(); }
  } else if (gesture && gesture.kind === 'pinch' && pointers.size >= 2) {
    const [a, b] = [...pointers.values()];
    const z = clamp(gesture.z * spread(a, b) / gesture.d, 0.12, 3);
    const bx = (gesture.mx - gesture.cx) / gesture.z, by = (gesture.my - gesture.cy) / gesture.z;
    cam.z = z;
    cam.x = (a.x + b.x) / 2 - bx * z;
    cam.y = (a.y + b.y) / 2 - by * z;
    requestDraw();
  }
});
function endPointer(e) {
  if (!pointers.has(e.pointerId)) return;
  pointers.delete(e.pointerId);
  if (gesture && gesture.kind === 'pan' && !gesture.moved && e.type === 'pointerup') tapAt(e.clientX, e.clientY);
  if (!pointers.size) gesture = null;
  else if (gesture && gesture.kind === 'pinch') {
    const [p] = [...pointers.values()];
    gesture = { kind: 'pan', sx: p.x, sy: p.y, cx: cam.x, cy: cam.y, moved: true };
  }
}
canvas.addEventListener('pointerup', endPointer);
canvas.addEventListener('pointercancel', endPointer);
canvas.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && hover) { hover = null; requestDraw(); } });
canvas.addEventListener('wheel', e => { e.preventDefault(); zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0016)); }, { passive: false });

/* ══════════ home demo: two computers playing a quick board ══════════ */
const demo = (() => {
  const c = $('#demo');
  const dctx = c.getContext('2d');
  const colors = [COLORS[0], COLORS[1]];
  let g = newGame('quick', 2, 0), timer = 0, hold = 0;

  function paint() {
    const r = c.getBoundingClientRect();
    if (!r.width) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), pad = 12;
    c.width = Math.round(r.width * dpr);
    c.height = Math.round(r.height * dpr);
    const z = (r.width - pad * 2) / (g.cols * GAP);
    dctx.setTransform(1, 0, 0, 1, 0, 0);
    dctx.clearRect(0, 0, c.width, c.height);
    dctx.setTransform(dpr * z, 0, 0, dpr * z, dpr * pad, dpr * pad);
    paintBoard(dctx, g, colors, { glow: 8 });
  }
  function step() {
    if (g.over) {
      if (++hold > 5) { hold = 0; g = newGame('quick', 2, 0); }
    } else {
      const [kind, i] = botMove(g);
      play(g, g.turn, kind, i);
    }
    paint();
  }
  return {
    run() {
      if (reduceMotion) {
        g = newGame('quick', 2, 0);
        for (let n = 0; n < 34 && !g.over; n++) { const [kind, i] = botMove(g); play(g, g.turn, kind, i); }
        paint();
        return;
      }
      paint();
      if (!timer) timer = setInterval(() => { if (!document.hidden) step(); }, 480);
    },
    stop() { clearInterval(timer); timer = 0; },
    paint,
  };
})();

/* ══════════ wiring ══════════ */
$('#name').addEventListener('input', e => { S.name = e.target.value.slice(0, 16); store.set('name', S.name); homeError(''); });
$('#swatches').addEventListener('click', e => {
  const b = e.target.closest('[data-c]');
  if (!b) return;
  S.color = b.dataset.c;
  store.set('color', S.color);
  renderHome();
});
$('#create').addEventListener('click', createRoom);
$('#joinForm').addEventListener('submit', e => { e.preventDefault(); joinRoom($('#code').value); });
$('#startLocal').addEventListener('click', startLocal);
$('#resume').addEventListener('click', () => { const l = loadLocal(); if (l) beginLocal(l); });
$('#lang').addEventListener('click', () => { lang = lang === 'fa' ? 'en' : 'fa'; store.set('lang', lang); applyLang(); });

$('#copyLink').addEventListener('click', async () => {
  const link = `${location.origin}${location.pathname}?room=${S.room.code}`;
  try { await navigator.clipboard.writeText(link); toast(t('copied')); } catch { toast(link); }
});
$('#startOnline').addEventListener('click', () => send({ t: 'start', size: S.room.size }));
$('#leaveLobby').addEventListener('click', leaveRoom);

$('#leaveGame').addEventListener('click', () => {
  if (S.mode === 'local') { goHome(); return; }
  const playing = S.room && S.room.phase === 'playing' && S.you >= 0;
  if (!playing || confirm(t('leaveConfirm'))) leaveRoom();
});
$('#zoomIn').addEventListener('click', () => zoomAt(innerWidth / 2, innerHeight / 2, 1.25));
$('#zoomOut').addEventListener('click', () => zoomAt(innerWidth / 2, innerHeight / 2, 0.8));
$('#zoomFit').addEventListener('click', fit);
$('#turn').addEventListener('click', e => { if (e.target.closest('#showOver')) { S.overHidden = false; renderGame(); } });
$('#overActions').addEventListener('click', e => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'again') { if (S.mode === 'local') restartLocal(); else send({ t: 'start' }); }
  else if (act === 'room') send({ t: 'lobby' });
  else if (act === 'home') goHome();
  else if (act === 'leave') leaveRoom();
  else if (act === 'view') { S.overHidden = true; renderGame(); }
});

document.addEventListener('keydown', e => {
  if (S.screen !== 'game' || e.target.closest('input')) return;
  if (e.key === '+' || e.key === '=') zoomAt(innerWidth / 2, innerHeight / 2, 1.25);
  else if (e.key === '-') zoomAt(innerWidth / 2, innerHeight / 2, 0.8);
  else if (e.key === '0') fit();
});
addEventListener('resize', () => { if (S.screen === 'game') sizeCanvas(); else if (S.screen === 'home') demo.paint(); });

applyLang();
show('home');
const invite = new URLSearchParams(location.search).get('room');
if (invite) {
  $('#code').value = invite.toUpperCase();
  if (S.name.trim()) joinRoom(invite);
  else { homeError(t('joinPrompt', { code: invite.toUpperCase() })); $('#name').focus(); }
}
