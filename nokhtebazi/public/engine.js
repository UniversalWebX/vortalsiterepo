/* ═══════════════════════════════════════════════════════════════
   Nokhtebazi rules: Dots and Boxes as pure functions.
   The browser and the server both import this file, so a move means
   exactly the same thing on every device and on the server.

   A board of cols × rows boxes has:
     h[i]  horizontal lines, (rows + 1) × cols, i = y * cols + x
     v[i]  vertical lines,   rows × (cols + 1), i = y * (cols + 1) + x
     boxes[b]               rows × cols,       b = y * cols + x
   Each holds the player index that drew or claimed it, or -1.
   ═══════════════════════════════════════════════════════════════ */

export const SIZES = {
  quick:    { cols: 5,  rows: 5 },
  classic:  { cols: 8,  rows: 8 },
  big:      { cols: 12, rows: 12 },
  marathon: { cols: 25, rows: 25 },
};

export function newGame(size, playerCount, starter = 0) {
  const key = SIZES[size] ? size : 'classic';
  const { cols, rows } = SIZES[key];
  return {
    size: key, cols, rows,
    h: new Array((rows + 1) * cols).fill(-1),
    v: new Array(rows * (cols + 1)).fill(-1),
    boxes: new Array(rows * cols).fill(-1),
    scores: new Array(playerCount).fill(0),
    turn: starter % playerCount,
    last: null,
    moves: 0,
    over: false,
  };
}

const lines = (g, kind) => (kind === 'h' ? g.h : g.v);

/** The four lines around box b, as [kind, index] pairs: top, bottom, left, right. */
export function boxLines(g, b) {
  const x = b % g.cols, y = (b / g.cols) | 0, W = g.cols + 1;
  return [['h', y * g.cols + x], ['h', (y + 1) * g.cols + x], ['v', y * W + x], ['v', y * W + x + 1]];
}

/** The one or two boxes a line borders. */
export function lineBoxes(g, kind, i) {
  const out = [];
  if (kind === 'h') {
    const x = i % g.cols, y = (i / g.cols) | 0;
    if (y > 0) out.push((y - 1) * g.cols + x);
    if (y < g.rows) out.push(y * g.cols + x);
  } else {
    const W = g.cols + 1, x = i % W, y = (i / W) | 0;
    if (x > 0) out.push(y * g.cols + x - 1);
    if (x < g.cols) out.push(y * g.cols + x);
  }
  return out;
}

export const sidesDrawn = (g, b) => boxLines(g, b).reduce((n, [k, i]) => n + (lines(g, k)[i] >= 0 ? 1 : 0), 0);

export function isFree(g, kind, i) {
  if (kind !== 'h' && kind !== 'v') return false;
  const list = lines(g, kind);
  return Number.isInteger(i) && i >= 0 && i < list.length && list[i] < 0;
}

/** Which player moves after `from`. `active(p)` lets the server skip players who have left. */
export function nextTurn(g, from, active = () => true) {
  const n = g.scores.length;
  for (let step = 1; step <= n; step++) {
    const p = (from + step) % n;
    if (active(p)) return p;
  }
  return (from + 1) % n;
}

/**
 * Draw one line for `player`. Closing a box claims it and keeps the turn.
 * Returns { ok, closed: [box indices] } or { ok: false, error: 'over' | 'turn' | 'taken' }.
 */
export function play(g, player, kind, i, active = () => true) {
  if (g.over) return { ok: false, error: 'over' };
  if (player !== g.turn) return { ok: false, error: 'turn' };
  if (!isFree(g, kind, i)) return { ok: false, error: 'taken' };

  lines(g, kind)[i] = player;
  g.moves++;
  g.last = { kind, i, by: player };
  const closed = lineBoxes(g, kind, i).filter(b => g.boxes[b] < 0 && sidesDrawn(g, b) === 4);
  for (const b of closed) { g.boxes[b] = player; g.scores[player]++; }

  if (g.boxes.every(owner => owner >= 0)) g.over = true;
  else if (!closed.length) g.turn = nextTurn(g, g.turn, active);
  return { ok: true, closed };
}

export function winners(g) {
  const best = Math.max(...g.scores);
  return g.scores.flatMap((s, i) => (s === best ? [i] : []));
}

/* ---------- computer opponent ----------
   1. Close any box that is one line from done.
   2. Otherwise draw a line that gives nothing away.
   3. Otherwise give away the shortest chain it can find. */
function freeLines(g) {
  const out = [];
  g.h.forEach((o, i) => { if (o < 0) out.push(['h', i]); });
  g.v.forEach((o, i) => { if (o < 0) out.push(['v', i]); });
  return out;
}

// How many boxes the opponent could take in a row after this line is drawn.
function giveaway(g, kind, i) {
  const sim = { ...g, h: g.h.slice(), v: g.v.slice() };
  lines(sim, kind)[i] = 0;
  const done = new Set();
  let taken = 0, changed = true;
  while (changed) {
    changed = false;
    for (let b = 0; b < g.boxes.length; b++) {
      if (g.boxes[b] >= 0 || done.has(b)) continue;
      const missing = boxLines(sim, b).filter(([k, j]) => lines(sim, k)[j] < 0);
      if (missing.length === 0) { done.add(b); taken++; changed = true; }
      else if (missing.length === 1) { const [k, j] = missing[0]; lines(sim, k)[j] = 0; changed = true; }
    }
  }
  return taken;
}

function shuffled(list, rand) {
  const a = list.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = (rand() * (i + 1)) | 0; [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

export function botMove(g, rand = Math.random) {
  const free = freeLines(g);
  const closer = free.find(([k, i]) => lineBoxes(g, k, i).some(b => g.boxes[b] < 0 && sidesDrawn(g, b) === 3));
  if (closer) return closer;

  const safe = free.filter(([k, i]) => lineBoxes(g, k, i).every(b => sidesDrawn(g, b) < 2));
  if (safe.length) return safe[(rand() * safe.length) | 0];

  const pool = free.length > 60 ? shuffled(free, rand).slice(0, 60) : free;
  let best = pool[0], cost = Infinity;
  for (const [k, i] of pool) {
    const c = giveaway(g, k, i);
    if (c < cost) { best = [k, i]; cost = c; }
  }
  return best;
}
