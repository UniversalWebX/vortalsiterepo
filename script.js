(() => {
  const V = window.Vortal;
  const esc = V.esc;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Small seeded RNG so the pixel art comes out the same on every load.
  function rng(seed) {
    return () => {
      seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rgb = h => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  const put = (d, i, c, a = 255) => { d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = a; };
  const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

  /* ---------- Products ---------- */
  const products = V.products();
  const live = products.filter(p => p.status === 'released');
  const soon = products.filter(p => p.status === 'soon');
  const cat = p => V.CATEGORIES[p.category];
  const names = list => list.length < 3
    ? list.map(p => p.name).join(' and ')
    : `${list.slice(0, -1).map(p => p.name).join(', ')}, and ${list[list.length - 1].name}`;

  const richText = s => esc(s).replace(/`([^`]{1,24})`/g, '<kbd>$1</kbd>');

  function featureHTML(f) {
    const body = f.text.includes('→')
      ? `<ol class="steps">${f.text.split('→').map(s => s.trim()).filter(Boolean).map(s => `<li>${esc(s)}</li>`).join('')}</ol>`
      : esc(f.text);
    return `<div><dt>${esc(f.label)}</dt><dd>${body}</dd></div>`;
  }

  function visualHTML(p) {
    if (p.visual === 'claims') {
      return `
        <figure class="viz">
          <div class="viz__head"><span>Claims map</span><span>Illustration</span></div>
          <canvas class="claims" width="160" height="96" role="img" aria-label="Illustration of a chunk map with three faction territories, open wilderness, and a contested border under siege"></canvas>
          <figcaption class="viz__foot">
            <ul class="legend">
              <li><i class="sw sw--claim"></i>Faction claims</li>
              <li><i class="sw sw--wild"></i>Wilderness</li>
              <li><i class="sw sw--siege"></i>Under siege</li>
            </ul>
            <span>1 cell = 1 chunk = 16 &times; 16 blocks</span>
          </figcaption>
        </figure>`;
    }
    if (p.visual === 'board') {
      return `
        <figure class="viz">
          <div class="viz__head"><span>The Line &middot; 40 spaces</span><span>Illustration</span></div>
          <div class="board" role="img" aria-label="A 40-space property board loop with a player token on Illinois Avenue">
            <div class="board__center">
              <span class="board__kicker">You bring the board.</span>
              <strong class="board__title">${esc(p.name)} runs the rest.</strong>
              <span class="board__sub">Bank &middot; Deeds &middot; Rent &middot; Cards &middot; Jail</span>
            </div>
          </div>
          <figcaption class="viz__foot"><span>&ldquo;Advance to Illinois Avenue. If you pass GO, collect $200.&rdquo;</span></figcaption>
        </figure>`;
    }
    return `
      <figure class="viz">
        <div class="viz__head"><span>${esc(cat(p).group)}</span><span>${esc(V.STATUSES[p.status])}</span></div>
        <div class="viz__stage"><span class="px px--xl" data-icon="${cat(p).icon}"></span></div>
        <figcaption class="viz__foot"><span>${esc(p.name)}</span></figcaption>
      </figure>`;
  }

  function releaseHTML(p, i) {
    const feats = p.features.filter(f => f.label || f.text);
    const url = V.safeUrl(p.link.url);
    return `
      <article class="release${i % 2 ? ' release--flip' : ''}" id="${esc(p.id)}" style="--accent:${V.shadeHex(p.shade)}">
        <div class="release__copy">
          <div class="release__tags">
            <span class="tag">${esc(cat(p).label)}</span>
            ${p.spec ? `<span class="spec">${esc(p.spec)}</span>` : ''}
          </div>
          <h3 class="release__name">${esc(p.name)}</h3>
          ${p.summary ? `<p class="release__lede">${esc(p.summary)}</p>` : ''}
          ${feats.length ? `<dl class="features">${feats.map(featureHTML).join('')}</dl>` : ''}
          ${p.note ? `<p class="release__note">${richText(p.note)}</p>` : ''}
          ${url ? `<a class="btn btn--solid" href="${esc(url)}" target="_blank" rel="noopener">${esc(p.link.label || `Open ${p.name}`)} <span aria-hidden="true">&#8599;</span></a>` : ''}
        </div>
        ${visualHTML(p)}
      </article>`;
  }

  function soonHTML(p) {
    return `
      <li class="soon__item" id="${esc(p.id)}" style="--accent:${V.shadeHex(p.shade)}">
        <span class="px soon__icon" data-icon="${cat(p).icon}"></span>
        <div class="soon__head">
          <h3 class="soon__name">${esc(p.name)}</h3>
          <span class="soon__cat">${esc(cat(p).label)}</span>
        </div>
        <p class="soon__text">${esc(p.summary)}</p>
        <span class="pill pill--soon">Coming soon</span>
      </li>`;
  }

  document.getElementById('release-list').innerHTML = live.length
    ? live.map(releaseHTML).join('')
    : '<p class="empty">Nothing released yet. Check back soon.</p>';
  document.getElementById('releases-meta').textContent = `${live.length} out now · ${soon.length} coming soon`;

  const soonSection = document.getElementById('soon');
  if (soon.length) {
    document.getElementById('soon-list').innerHTML = soon.map(soonHTML).join('');
    document.getElementById('soon-meta').textContent = `${soon.length} in the works`;
  } else {
    soonSection.hidden = true;
  }

  // What we make: one entry per category, with what's out and what's next.
  const link = p => `<a href="#${esc(p.id)}">${esc(p.name)}</a>`;
  document.getElementById('disciplines').innerHTML = Object.entries(V.CATEGORIES).map(([key, c]) => {
    const out = live.filter(p => p.category === key);
    const next = soon.filter(p => p.category === key);
    let status = '';
    if (out.length) status += `<p class="disc__status is-live">Out now: ${out.map(link).join(', ')}</p>`;
    if (next.length) status += `<p class="disc__status is-soon">Up next: ${next.map(link).join(', ')}</p>`;
    if (!status) status = '<p class="disc__status">Coming soon</p>';
    return `
      <li class="disc" style="--accent:${V.shadeHex(c.shade)}">
        <span class="px" data-icon="${c.icon}"></span>
        <h3 class="disc__name">${esc(c.group)}</h3>
        <p class="disc__text">${esc(c.blurb)}</p>
        <div class="disc__foot">${status}</div>
      </li>`;
  }).join('');

  if (soon.length) {
    document.getElementById('next-copy').textContent =
      `Up next: ${names(soon)}. Geometry Dash mods and our first physical devices are on the bench too. Check back here for new drops.`;
  }

  document.getElementById('foot-links').insertAdjacentHTML('afterbegin',
    live.map(p => `<li><a href="#${esc(p.id)}">${esc(p.name)}</a></li>`).join(''));

  /* ---------- Products dropdown ---------- */
  const menuBtn = document.getElementById('menu-btn');
  const menu = document.getElementById('menu-products');
  const menuGroup = (title, list) => list.length ? `
    <div class="menu__group">
      <p class="menu__label">${title}</p>
      ${list.map(p => `
        <a class="menu__item" href="#${esc(p.id)}" style="--accent:${V.shadeHex(p.shade)}">
          <span class="px menu__icon" data-icon="${cat(p).icon}"></span>
          <span class="menu__text">
            <span class="menu__name">${esc(p.name)}</span>
            <span class="menu__cat">${esc(cat(p).label)}</span>
          </span>
        </a>`).join('')}
    </div>` : '';
  menu.innerHTML = (menuGroup('Out now', live) + menuGroup('Coming soon', soon)) ||
    '<p class="menu__label">No products yet</p>';

  const setMenu = open => { menu.hidden = !open; menuBtn.setAttribute('aria-expanded', String(open)); };
  menuBtn.addEventListener('click', () => setMenu(menu.hidden));
  menu.addEventListener('click', e => { if (e.target.closest('a')) setMenu(false); });
  document.addEventListener('click', e => { if (!menu.hidden && !e.target.closest('.menu')) setMenu(false); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !menu.hidden) { setMenu(false); menuBtn.focus(); }
  });
  menu.addEventListener('keydown', e => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = [...menu.querySelectorAll('.menu__item')];
    const i = items.indexOf(document.activeElement);
    e.preventDefault();
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
  });
  menuBtn.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setMenu(true); menu.querySelector('.menu__item')?.focus(); }
  });

  V.paintIcons();

  /* ---------- Hero portal ---------- */
  const portal = document.getElementById('portal');
  if (portal) {
    const ctx = portal.getContext('2d');
    const W = 128, H = 144, B = 16;             // 16px textures, like the game
    const FX = 16, FY = 16, FW = 6 * B, FH = 7 * B;
    const IX = FX + B, IY = FY + B, IW = 4 * B, IH = 5 * B;
    const OBS = ['#0C0914', '#120D1E', '#181128', '#1F1733', '#2C2148', '#3E2F66'].map(rgb);
    const PAL = ['#1A0538', '#2B0961', '#44118F', '#6019C2', '#8130EE', '#A862FF', '#D5B2FF'].map(rgb);
    // Tinted copies of the palette so the swirl drifts between orchid and periwinkle.
    const tint = hex => { const t = rgb(hex); return PAL.map(c => mix(c, t.map(v => v * Math.max(...c) / 255), .55)); };
    const ORCHID = tint(V.shadeHex('orchid')), PERI = tint(V.shadeHex('periwinkle'));
    const SPARKS = [PAL[5], PAL[6], ORCHID[6], PERI[6]];
    const img = ctx.createImageData(W, H);
    const d = img.data;
    const r = rng(7);

    // Obsidian frame, baked once.
    const base = new Uint8ClampedArray(W * H * 4);
    for (let y = FY; y < FY + FH; y++) {
      for (let x = FX; x < FX + FW; x++) {
        if (x >= IX && x < IX + IW && y >= IY && y < IY + IH) continue;
        const bx = (x - FX) % B, by = (y - FY) % B;
        const n = r();
        let k = n < .5 ? 1 : n < .78 ? 2 : n < .96 ? 0 : 3;
        if (r() < .035) k = 4;
        if (r() < .01) k = 5;
        if (bx === 0 || by === 0) k = Math.min(k + 1, 4);
        if (bx === B - 1 || by === B - 1) k = 0;
        put(base, (y * W + x) * 4, OBS[k]);
      }
    }

    const noise = Float32Array.from({ length: IW * IH }, () => r() - .5);
    const particles = [];
    let t = 1.3, ignite = reduceMotion ? 1 : 0;

    function draw() {
      d.set(base);
      for (let ly = 0; ly < IH; ly++) {
        for (let lx = 0; lx < IW; lx++) {
          const dx = lx - IW / 2 + .5, dy = (ly - IH / 2 + .5) * .8;
          const rad = Math.hypot(dx, dy), ang = Math.atan2(dy, dx);
          const nz = noise[ly * IW + lx];
          const v = Math.sin(rad * .33 - t * 2.4 + ang * 2) * .55
                  + Math.sin(lx * .21 + ly * .13 + t * 1.3) * .3
                  + Math.sin(ly * .27 - lx * .08 - t * 1.9) * .25
                  + nz * Math.sin(t * 3 + nz * 40) * .5;
          const glow = 1 - rad / 40;
          let k = Math.floor((v + 1.2) / 2.4 * 5 + glow * 2.2 - (1 - ignite) * 7);
          k = k < 0 ? 0 : k > 6 ? 6 : k;
          const w = Math.sin(lx * .05 + ly * .035 + t * .6);
          put(d, ((IY + ly) * W + IX + lx) * 4, w > 0 ? mix(PAL[k], ORCHID[k], w) : mix(PAL[k], PERI[k], -w));
        }
      }
      ctx.putImageData(img, 0, 0);

      // Loose particles drifting out of the portal.
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx; p.y += p.vy; p.vx *= .985; p.vy *= .985; p.life++;
        if (p.life > p.max || p.x < 0 || p.y < 0 || p.x >= W || p.y >= H) { particles.splice(i, 1); continue; }
        const c = p.c;
        ctx.globalAlpha = 1 - p.life / p.max;
        ctx.fillStyle = `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;
        ctx.fillRect(Math.round(p.x), Math.round(p.y), 1, 1);
      }
      ctx.globalAlpha = 1;
    }

    function spawn() {
      if (particles.length > 40 || ignite < .5) return;
      for (let i = 0; i < 2; i++) {
        particles.push({
          x: IX + r() * IW, y: IY + r() * IH,
          vx: (r() - .5) * 1.3, vy: (r() - .5) * 1.3 - .2,
          life: 0, max: 30 + r() * 55, c: SPARKS[(r() * SPARKS.length) | 0],
        });
      }
    }

    if (reduceMotion) {
      draw();
    } else {
      const STEP = 1000 / 20;  // 20 ticks a second
      let start = 0, last = 0, raf = 0, visible = true;
      const loop = now => {
        raf = requestAnimationFrame(loop);
        if (!start) start = now;
        if (now - last < STEP) return;
        last = now;
        const p = Math.min(1, (now - start) / 1100);
        ignite = 1 - Math.pow(1 - p, 3);
        t += .05;
        spawn();
        draw();
      };
      const run = () => { if (!raf && visible && !document.hidden) raf = requestAnimationFrame(loop); };
      const stop = () => { cancelAnimationFrame(raf); raf = 0; };
      new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible ? run() : stop(); }).observe(portal);
      document.addEventListener('visibilitychange', () => (document.hidden ? stop() : run()));
      draw();
      run();
    }
  }

  /* ---------- Claims map illustration ---------- */
  function drawClaims(canvas) {
    const ctx = canvas.getContext('2d');
    const COLS = 20, ROWS = 12, C = 8, W = COLS * C, H = ROWS * C;
    const r = rng(21);
    const WILD = ['#140F1E', '#17112A', '#1B142F', '#1F1734'].map(rgb);
    const WILD_EDGE = rgb('#251C3B');
    const SIEGE = rgb('#FFB35C');
    const factions = [
      { x: 4.5, y: 4.2, r: 4.3, c: rgb(V.shadeHex('violet')) },
      { x: 11.2, y: 7.6, r: 4.5, c: rgb(V.shadeHex('orchid')) },
      { x: 16.6, y: 2.8, r: 3.4, c: rgb(V.shadeHex('periwinkle')) },
    ];

    const owner = [];
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        let best = -1, bestD = Infinity;
        factions.forEach((f, i) => {
          const dist = Math.hypot(x + .5 - f.x, y + .5 - f.y) + (r() - .5) * 1.4;
          if (dist < f.r && dist < bestD) { best = i; bestD = dist; }
        });
        owner.push(best);
      }
    }
    const at = (x, y) => (x < 0 || y < 0 || x >= COLS || y >= ROWS) ? -2 : owner[y * COLS + x];

    // Chunks on the violet/orchid border are contested.
    const siege = owner.map((o, i) => {
      if (o !== 0 && o !== 1) return false;
      const x = i % COLS, y = (i / COLS) | 0, other = o === 0 ? 1 : 0;
      return [at(x - 1, y), at(x + 1, y), at(x, y - 1), at(x, y + 1)].includes(other) && r() < .75;
    });

    const img = ctx.createImageData(W, H);
    const d = img.data;
    for (let cy = 0; cy < ROWS; cy++) {
      for (let cx = 0; cx < COLS; cx++) {
        const o = at(cx, cy), f = factions[o];
        const s = siege[cy * COLS + cx];
        for (let py = 0; py < C; py++) {
          for (let px = 0; px < C; px++) {
            let col = WILD[(r() * WILD.length) | 0];
            if (o < 0) {
              if (px === 0 || py === 0) col = WILD_EDGE;
            } else {
              col = mix(col, f.c, .34);
              const edge =
                (px === 0 && at(cx - 1, cy) !== o) || (px === C - 1 && at(cx + 1, cy) !== o) ||
                (py === 0 && at(cx, cy - 1) !== o) || (py === C - 1 && at(cx, cy + 1) !== o);
              if (s && (px + py) % 4 < 2) col = mix(col, SIEGE, .85);
              if (edge) col = f.c;
            }
            put(d, ((cy * C + py) * W + cx * C + px) * 4, col);
          }
        }
      }
    }
    ctx.putImageData(img, 0, 0);
  }
  document.querySelectorAll('canvas.claims').forEach(drawClaims);

  /* ---------- Board loop illustration ---------- */
  const SPACES = [
    'go', 'br', 'cc', 'br', 'tax', 'rr', 'lb', 'ch', 'lb', 'lb',
    'jail', 'pk', 'ut', 'pk', 'pk', 'rr', 'or', 'cc', 'or', 'or',
    'fp', 'rd', 'ch', 'rd', 'rd', 'rr', 'ye', 'ye', 'ut', 'ye',
    'gj', 'gr', 'gr', 'cc', 'gr', 'rr', 'ch', 'db', 'tax', 'db',
  ];
  const GROUP_COLORS = { br: '#8B5A3C', lb: '#9AD7F2', pk: '#D862B5', or: '#F0983C', rd: '#E0463E', ye: '#EFD04A', gr: '#3DAA68', db: '#4460E0' };
  const GLYPH = { go: 'GO', jail: 'JAIL', fp: 'FREE', gj: '→JAIL', rr: 'RR', ut: 'UT', ch: '?', cc: 'CC', tax: '$' };
  const TOKEN_AT = 24; // Illinois Avenue
  const place = i => {
    if (i <= 10) return [11, 11 - i, 'b'];
    if (i <= 20) return [11 - (i - 10), 1, 'l'];
    if (i <= 30) return [1, 1 + (i - 20), 't'];
    return [1 + (i - 30), 11, 'r'];
  };

  document.querySelectorAll('.board').forEach(board => {
    const frag = document.createDocumentFragment();
    SPACES.forEach((type, i) => {
      const [row, col, side] = place(i);
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.setAttribute('aria-hidden', 'true');
      cell.style.gridRow = row;
      cell.style.gridColumn = col;
      if (i % 10 === 0) cell.classList.add('cell--corner');
      if (type === 'go') cell.classList.add('cell--go');
      if (GROUP_COLORS[type]) {
        cell.classList.add('cell--prop', `side-${side}`);
        cell.style.setProperty('--c', GROUP_COLORS[type]);
      } else {
        cell.textContent = GLYPH[type];
      }
      if (i === TOKEN_AT) {
        const token = document.createElement('span');
        token.className = 'token';
        cell.appendChild(token);
      }
      frag.appendChild(cell);
    });
    board.appendChild(frag);
  });
})();
