(() => {
  const V = window.Vortal;
  const esc = V.esc;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Volatile 1.0 countdown ----------
     Counts down to the release; the glow moves to a new shade of yellow or
     green every hour (the same shade for everyone during that hour). */
  const RELEASE = V.RELEASE;   // October 1, 5:30 PM Pacific (store.js)
  const GLOWS = ['#FFD84A', '#B8F03C', '#F2C230', '#8BE04E', '#FFE873', '#6FD66A',
    '#E8D23A', '#A4F07A', '#FFC940', '#55E07A', '#D9F24A', '#C8E83A'];
  const COUNT_HTML = `<div class="vcount" data-countdown hidden>
            <p class="vcount__label"><span class="vcount__dot" aria-hidden="true"></span>Volatile 1.0 · official release</p>
            <div class="vcount__time" role="timer" aria-live="off">
              <span class="vcount__unit"><b data-u="d">0</b><i>days</i></span>
              <span class="vcount__unit"><b data-u="h">00</b><i>hours</i></span>
              <span class="vcount__unit"><b data-u="m">00</b><i>minutes</i></span>
              <span class="vcount__unit"><b data-u="s">00</b><i>seconds</i></span>
            </div>
            <p class="vcount__when" data-when></p>
          </div>`;
  function mountCountdowns(root) {
    root.querySelectorAll('[data-countdown]').forEach(el => {
      if (el.dataset.live) return;
      el.dataset.live = '1';
      el.hidden = false;
      const when = el.querySelector('[data-when]');
      if (when) {
        const local = new Date(RELEASE).toLocaleString(undefined, { weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });
        const pacific = new Date(RELEASE).getTimezoneOffset() === 420;   // the visitor is on Pacific time too
        when.textContent = pacific ? 'Thursday, October 1 · 5:30 PM Pacific' : `October 1 · 5:30 PM Pacific  ·  ${local} where you are`;
      }
      const set = (u, v) => { const b = el.querySelector(`[data-u="${u}"]`); if (b && b.textContent !== v) b.textContent = v; };
      let hour = -1;
      const tick = () => {
        const now = Date.now();
        const h = Math.floor(now / 3600000);
        if (h !== hour) {
          hour = h;
          el.style.setProperty('--glow', GLOWS[h % GLOWS.length]);
        }
        let left = Math.max(0, RELEASE - now);
        if (left <= 0) {
          el.classList.add('is-out');
          el.querySelector('.vcount__label').lastChild.textContent = 'Volatile 1.0 is out now';
          el.querySelector('.vcount__time').hidden = true;
          if (when) when.hidden = true;
          return;
        }
        const d = Math.floor(left / 86400000); left -= d * 86400000;
        const hh = Math.floor(left / 3600000); left -= hh * 3600000;
        const mm = Math.floor(left / 60000); left -= mm * 60000;
        const ss = Math.floor(left / 1000);
        set('d', String(d));
        set('h', String(hh).padStart(2, '0'));
        set('m', String(mm).padStart(2, '0'));
        set('s', String(ss).padStart(2, '0'));
        setTimeout(tick, 1000 - (now % 1000) + 5);
      };
      tick();
    });
  }

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

  /* ---------- Products and pages ----------
     vortal.space/ is the home page, vortal.space/<id> is that product's page,
     and vortal.space/contact is the contact form. Every address serves this
     same index.html; this decides what to show. */
  const products = V.products();
  const listed = products.filter(p => p.status !== 'hidden');
  const live = listed.filter(p => p.status === 'released');
  const soon = listed.filter(p => p.status === 'soon');
  const cat = p => V.CATEGORIES[p.category];
  const href = p => `/${encodeURIComponent(p.id)}`;
  const names = list => list.length < 3
    ? list.map(p => p.name).join(' and ')
    : `${list.slice(0, -1).map(p => p.name).join(', ')}, and ${list[list.length - 1].name}`;

  let route = '';
  try { route = decodeURIComponent(location.pathname); } catch { route = location.pathname; }
  route = route.replace(/^\/index\.html$/i, '/').replace(/\/+$/, '').slice(1).toLowerCase();
  const current = route ? listed.find(p => p.id.toLowerCase() === route) : null;

  const richText = s => esc(s).replace(/`([^`]{1,24})`/g, '<kbd>$1</kbd>');
  const statusPill = p => `<span class="pill pill--${p.status}">${esc(V.STATUSES[p.status])}</span>`;

  function featureHTML(f) {
    const body = f.text.includes('→')
      ? `<ol class="steps">${f.text.split('→').map(s => s.trim()).filter(Boolean).map(s => `<li>${esc(s)}</li>`).join('')}</ol>`
      : esc(f.text);
    return `<div><dt>${esc(f.label)}</dt><dd>${body}</dd></div>`;
  }

  /* ---------- Downloads: one button for your platform, the rest in a dropdown ---------- */
  function myPlatform() {
    const ua = navigator.userAgent || '';
    if (/CrOS/.test(ua)) return 'chromebook';
    if (/Android/i.test(ua)) return 'android';
    if (/iPhone|iPad|iPod/.test(ua)) return '';
    if (/Mac/.test(ua)) return 'mac';
    if (/Win/.test(ua)) return 'windows';
    return '';
  }
  // list: [{label, url, platform, minor, hint}]; minor ones (the server) sit at the end
  function downloadsHTML(list, haz) {
    const dls = list.filter(d => V.safeUrl(d.url));
    if (!dls.length) return '';
    const mine = myPlatform();
    const main = dls.find(d => d.platform && d.platform === mine && !d.minor) || dls.find(d => !d.minor) || dls[0];
    const rest = [...dls.filter(d => !d.minor), ...dls.filter(d => d.minor)];
    return `
      <div class="dl">
        <a class="btn ${haz ? 'btn--haz' : 'btn--solid'} dl__main" href="${esc(main.url)}" target="_blank" rel="noopener">${esc(main.label)} <span aria-hidden="true">&#8595;</span></a>
        ${rest.length > 1 ? `
        <details class="dl__more">
          <summary class="btn ${haz ? 'btn--line btn--line-haz' : 'btn--line'}">All platforms <span class="dl__caret" aria-hidden="true">&#9662;</span></summary>
          <ul class="dl__menu">
            ${rest.map(d => `
            <li class="${d === main ? 'is-mine' : ''}${d.minor ? ' is-minor' : ''}">
              <a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.label)}${d === main ? ' <span class="dl__you">your device</span>' : ''}</a>
              ${d.hint ? `<small>${esc(d.hint)}</small>` : ''}
            </li>`).join('')}
          </ul>
        </details>` : ''}
      </div>`;
  }
  // close an open dropdown when you click elsewhere or press Escape
  document.addEventListener('click', e => document.querySelectorAll('.dl__more[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('.dl__more[open]').forEach(d => { d.open = false; }); });

  function actionsHTML(p) {
    const url = V.safeUrl(p.link.url), src = V.safeUrl(p.source), guide = V.safeUrl(p.guide.url);
    const more = p.more.filter(m => V.safeUrl(m.url));
    if (!url && !src && !guide && !more.length) return '';
    const several = url && more.length > 0;
    return `
      <div class="release__actions">
        ${several ? downloadsHTML([p.link, ...more], false) : ''}
        ${url && !several ? `<a class="btn btn--solid" href="${esc(url)}" target="_blank" rel="noopener">${esc(p.link.label || `Open ${p.name}`)} <span aria-hidden="true">&#8599;</span></a>` : ''}
        ${!several ? more.map(m => `<a class="btn btn--line" href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.label)} <span aria-hidden="true">&#8599;</span></a>`).join('') : ''}
        ${guide ? `<a class="btn ${url ? 'btn--line' : 'btn--solid'}" href="${esc(guide)}" target="_blank" rel="noopener">${esc(p.guide.label || 'Read the guide')} <span aria-hidden="true">&#8599;</span></a>` : ''}
        ${src ? `<a class="btn btn--line" href="${esc(src)}" target="_blank" rel="noopener">View source <span aria-hidden="true">&#8599;</span></a>` : ''}
      </div>`;
  }

  /* ---------- Product art ---------- */
  // Dots and Boxes illustration: a seeded game in progress, two players' lines and claimed boxes.
  let glowCount = 0;
  function dotsSVG(p) {
    const COLS = 8, ROWS = 5, S = 40, PAD = 20;
    const players = [V.shadeHex(p.shade), V.shadeHex('orchid')];
    const r = rng(9);
    const pick = () => (r() < .58 ? (r() < .5 ? 0 : 1) : -1);   // -1 = not drawn yet
    const hor = Array.from({ length: (ROWS + 1) * COLS }, pick);
    const ver = Array.from({ length: ROWS * (COLS + 1) }, pick);
    const H = (x, y) => hor[y * COLS + x], Vt = (x, y) => ver[y * (COLS + 1) + x];
    const glow = `dots-glow-${++glowCount}`;
    let out = `<defs><filter id="${glow}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;

    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        const sides = [H(x, y), H(x, y + 1), Vt(x, y), Vt(x + 1, y)];
        if (sides.every(s => s >= 0)) {
          out += `<rect x="${PAD + x * S + 6}" y="${PAD + y * S + 6}" width="${S - 12}" height="${S - 12}" rx="3" fill="${players[sides[(x + y) % 4]]}" opacity=".35"/>`;
        }
      }
    }
    const line = (x1, y1, x2, y2, who) => who < 0
      ? `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#1E1730" stroke-width="5" stroke-linecap="round"/>`
      : `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${players[who]}" stroke-width="5" stroke-linecap="round" filter="url(#${glow})"/>`;
    for (let y = 0; y <= ROWS; y++) for (let x = 0; x < COLS; x++) out += line(PAD + x * S, PAD + y * S, PAD + (x + 1) * S, PAD + y * S, H(x, y));
    for (let y = 0; y < ROWS; y++) for (let x = 0; x <= COLS; x++) out += line(PAD + x * S, PAD + y * S, PAD + x * S, PAD + (y + 1) * S, Vt(x, y));
    for (let y = 0; y <= ROWS; y++) for (let x = 0; x <= COLS; x++) out += `<circle cx="${PAD + x * S}" cy="${PAD + y * S}" r="3.5" fill="#6E6488"/>`;

    // another player's live cursor, as the game shows it
    const cx = PAD + 5.5 * S, cy = PAD + 2.45 * S;
    out += `<circle cx="${cx}" cy="${cy}" r="6" fill="${players[1]}"/>`;
    out += `<rect x="${cx + 10}" y="${cy - 26}" width="64" height="18" rx="4" fill="rgba(0,0,0,.8)"/>`;
    out += `<text x="${cx + 18}" y="${cy - 13}" fill="${players[1]}">Player 2</text>`;
    return out;
  }

  // The picture itself: used bare on cards and framed on product pages.
  function visualArt(p) {
    if (p.visual === 'shot') {
      return `<img class="shot" src="${esc(p.image)}" alt="Screenshot of ${esc(p.name)}" loading="lazy" decoding="async">`;
    }
    if (p.visual === 'dots') {
      return `<svg class="dots" viewBox="0 0 360 240" role="img" aria-label="Illustration of a Dots and Boxes game in progress, with two players' lines, claimed boxes, and another player's cursor">${dotsSVG(p)}</svg>`;
    }
    if (p.visual === 'claims') {
      return '<canvas class="claims" width="160" height="96" role="img" aria-label="Illustration of a chunk map with three faction territories, open wilderness, and a contested border under siege"></canvas>';
    }
    if (p.visual === 'giveaway') {
      // A Discord giveaway message, drawn in DonutDuck's own blue / pink / yellow.
      return `
        <div class="gw" role="img" aria-label="Illustration of a ${esc(p.name)} giveaway message in Discord: a five million prize in Double or Keep mode, with an Enter button showing 48 entries">
          <div class="gw__msg">
            <span class="gw__avatar"></span>
            <div class="gw__main">
              <div class="gw__who"><b>${esc(p.name)}</b><span class="gw__bot">BOT</span><span class="gw__time">Today at 18:04</span></div>
              <div class="gw__embed">
                <p class="gw__kicker">Giveaway &middot; #0007</p>
                <p class="gw__prize">$5m in-game money</p>
                <div class="gw__facts">
                  <span><i>Ends</i> in 2h 14m</span>
                  <span><i>Winners</i> 1</span>
                  <span><i>Mode</i> Double or Keep</span>
                </div>
              </div>
              <div class="gw__buttons"><span class="gw__btn gw__btn--enter">Enter &middot; 48</span><span class="gw__btn">Rules</span></div>
            </div>
          </div>
        </div>`;
    }
    if (p.visual === 'board') {
      return `
        <div class="board" role="img" aria-label="A 40-space property board loop with a player token on Illinois Avenue">
          <div class="board__center">
            <span class="board__kicker">You bring the board.</span>
            <strong class="board__title">${esc(p.name)} runs the rest.</strong>
            <span class="board__sub">Bank &middot; Deeds &middot; Rent &middot; Cards &middot; Jail</span>
          </div>
        </div>`;
    }
    return `<div class="viz__stage"><span class="px px--xl" data-icon="${cat(p).icon}"></span></div>`;
  }

  function visualHTML(p) {
    const frame = {
      dots: ['Dots &amp; boxes', '<span>Boards from 5 &times; 5 to 25 &times; 25</span><span>Close a box, go again</span>'],
      claims: ['Claims map', `<ul class="legend">
          <li><i class="sw sw--claim"></i>Faction claims</li>
          <li><i class="sw sw--wild"></i>Wilderness</li>
          <li><i class="sw sw--siege"></i>Under siege</li>
        </ul><span>1 cell = 1 chunk = 16 &times; 16 blocks</span>`],
      board: ['The Line &middot; 40 spaces', '<span>&ldquo;Advance to Illinois Avenue. If you pass GO, collect $200.&rdquo;</span>'],
      giveaway: ['Giveaway message', '<span>Double or Keep: keep the prize, or win again for twice as much</span>'],
      shot: ['In-game screenshot', `<span>${esc(p.caption || p.name)}</span>`],
    }[p.visual] || [esc(cat(p).group), `<span>${esc(p.name)}</span>`];
    return `
      <figure class="viz">
        <div class="viz__head"><span>${frame[0]}</span><span>${p.visual === 'icon' ? esc(V.STATUSES[p.status]) : p.visual === 'shot' ? 'Screenshot' : 'Illustration'}</span></div>
        ${visualArt(p)}
        <figcaption class="viz__foot">${frame[1]}</figcaption>
      </figure>`;
  }

  /* ---------- Building blocks ---------- */
  function cardHTML(p) {
    const haz = p.id === 'volatile';
    return `
      <a class="pcard${haz ? ' pcard--haz' : ''}" href="${href(p)}" style="--accent:${haz ? '#F29E2E' : V.shadeHex(p.shade)}">
        ${haz ? `<span class="haz-ribbon">${V.released() ? 'Version 1.0' : 'Update 1 Beta'}</span>` : ''}
        <div class="pcard__media">${visualArt(p)}${haz ? '<img class="haz-emblem" src="/files/volatile-emblem.png" alt="" aria-hidden="true">' : ''}</div>
        <div class="pcard__body">
          <div class="release__tags"><span class="tag">${esc(p.kind || cat(p).label)}</span>${statusPill(p)}</div>
          <h3 class="pcard__name">${esc(p.name)}</h3>
          ${p.summary ? `<p class="pcard__text">${esc(p.summary)}</p>` : ''}
          <span class="pcard__more">Details <span aria-hidden="true">&rarr;</span></span>
        </div>
      </a>`;
  }

  function soonHTML(p) {
    return `
      <li>
        <a class="soon__item" href="${href(p)}" style="--accent:${V.shadeHex(p.shade)}">
          <span class="px soon__icon" data-icon="${cat(p).icon}"></span>
          <span class="soon__head">
            <span class="soon__name">${esc(p.name)}</span>
            <span class="soon__cat">${esc(p.kind || cat(p).label)}</span>
          </span>
          <span class="soon__text">${esc(p.summary)}</span>
          <span class="pill pill--soon">Coming soon</span>
        </a>
      </li>`;
  }

  /* ---------- Videos (YouTube, loaded only when played) ---------- */
  function premiereText(at) {
    const d = new Date(at);
    const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    const pacific = d.getTimezoneOffset() === 420;
    const today = d.toDateString() === new Date().toDateString();
    const day = today ? 'today' : d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
    return `Premieres ${day} · ${time}${pacific ? ' PT' : ''}`;
  }
  function videosHTML(list) {
    return list.map(v => {
      const soon = v.premiere && v.premiere > Date.now();
      return `
        <figure class="vvid">
          <button class="vvid__play" type="button" data-yt="${esc(v.id)}" aria-label="Play: ${esc(v.title || 'video')}"
            style="background-image:url('https://i.ytimg.com/vi/${esc(v.id)}/hqdefault.jpg')">
            <span class="vvid__icon" aria-hidden="true"></span>
            ${soon ? `<span class="vvid__badge" data-premiere="${v.premiere}">${esc(premiereText(v.premiere))}</span>` : ''}
          </button>
          ${v.title ? `<figcaption class="vvid__cap">${esc(v.title)}</figcaption>` : ''}
        </figure>`;
    }).join('');
  }
  function wireVideos(root) {
    root.addEventListener('click', e => {
      const b = e.target.closest('[data-yt]');
      if (!b) return;
      const f = document.createElement('iframe');
      f.className = 'vvid__frame';
      f.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(b.dataset.yt)}?autoplay=1&rel=0`;
      f.title = b.getAttribute('aria-label').replace(/^Play: /, '');
      f.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
      f.allowFullscreen = true;
      f.referrerPolicy = 'strict-origin-when-cross-origin';
      b.replaceWith(f);
    });
    // the premiere badge goes away when it starts
    root.querySelectorAll('[data-premiere]').forEach(el => {
      const left = +el.dataset.premiere - Date.now();
      if (left < 2147483647) setTimeout(() => el.remove(), Math.max(0, left));
    });
  }

  function productPageHTML(p) {
    const feats = p.features.filter(f => f.label || f.text);
    const section = p.status === 'soon' ? ['soon', 'Coming soon'] : ['releases', 'Released'];
    const others = [...live, ...soon].filter(o => o !== p).slice(0, 3);
    const body = feats.length || p.note
      ? `
        <section class="wrap product-body">
          <header class="section-head section-head--tight"><h2>What it does</h2></header>
          ${feats.length ? `<dl class="features features--page">${feats.map(featureHTML).join('')}</dl>` : ''}
          ${p.note ? `<p class="callout">${richText(p.note)}</p>` : ''}
          ${p.howtos.map(h => `
          <details class="howto" id="${esc(h.id)}">
            <summary>${esc(h.title)}</summary>
            <ol>${h.steps.map(st => `<li>${richText(st)}</li>`).join('')}</ol>
          </details>`).join('')}
        </section>`
      : `
        <section class="wrap product-body">
          <p class="product__soon">Part of Vortal's <a href="/#make">${esc(cat(p).group)}</a>: ${esc(cat(p).blurb)}</p>
        </section>`;
    const gallery = p.gallery.length ? `
        <section class="wrap vgal vgal--page">
          <header class="section-head section-head--tight"><h2>Screenshots</h2></header>
          <div class="vgal__grid">${galleryHTML(p.gallery)}</div>
        </section>` : '';
    const host = p.hosting ? hostingHTML(p.hosting) : '';
    const vids = p.videos.length ? `
        <section class="wrap vvids vvids--page" id="videos">
          <header class="section-head section-head--tight"><h2>Videos</h2></header>
          <div class="vvids__grid">${videosHTML(p.videos)}</div>
        </section>` : '';
    const haz = p.id === 'volatile';
    return `
      <article class="product${haz ? ' product--haz' : ''}" style="--accent:${haz ? '#F29E2E' : V.shadeHex(p.shade)}">
        <section class="product-hero">
          <div class="wrap product-hero__grid">
            <div class="product-hero__copy">
              <nav class="crumbs" aria-label="Breadcrumb">
                <a href="/">Vortal</a><span aria-hidden="true">/</span>
                <a href="/#${section[0]}">${section[1]}</a><span aria-hidden="true">/</span>
                <span aria-current="page">${esc(p.name)}</span>
              </nav>
              <div class="release__tags">
                <span class="tag">${esc(p.kind || cat(p).label)}</span>${statusPill(p)}
                ${p.spec ? `<span class="spec">${esc(p.spec)}</span>` : ''}
              </div>
              <h1 class="product__name">${esc(p.name)}</h1>
              ${p.summary ? `<p class="product__lede">${esc(p.summary)}</p>` : ''}
              ${actionsHTML(p)}
              <p class="product__ask">Questions about ${esc(p.name)}? <a href="/contact?topic=${encodeURIComponent(p.name)}">Send us a message</a></p>
            </div>
            ${visualHTML(p)}
          </div>
          ${p.id === 'volatile' ? `<div class="wrap vcount-wide">${COUNT_HTML}</div>` : ''}
        </section>
        ${vids}
        ${haz ? '<section class="wrap vcom-sec" id="community"></section>' : ''}
        ${gallery}
        ${body}
        ${host}
        ${others.length ? `
        <section class="wrap more">
          <header class="section-head">
            <h2>More from Vortal</h2>
            <p class="section-head__meta"><a href="/#releases">Everything we make</a></p>
          </header>
          <div class="pgrid">${others.map(cardHTML).join('')}</div>
        </section>` : ''}
      </article>`;
  }

  /* ---------- "Host a server" guide ---------- */
  function hostingHTML(h) {
    const kv = (rows, cls) => rows.length ? `
          <dl class="vhost__kv ${cls}">${rows.map(r => `<div><dt><code>${esc(r[0])}</code></dt><dd>${esc(r[1])}</dd></div>`).join('')}</dl>` : '';
    return `
        <section class="wrap vhost" id="server" aria-labelledby="server-title">
          <header class="section-head section-head--tight">
            <p class="eyebrow eyebrow--haz">Dedicated servers</p>
            <h2 id="server-title">${esc(h.title)}</h2>
          </header>
          ${h.lede ? `<p class="vhost__lede">${esc(h.lede)}</p>` : ''}
          <div class="vhost__options">${h.options.map(o => `
            <article class="vhost__card">
              <header class="vhost__head"><h3>${esc(o.name)}</h3>${o.tag ? `<span class="vbadge">${esc(o.tag)}</span>` : ''}</header>
              <ol class="vhost__steps">${o.steps.map(s => `
                <li>${s.text ? `<p>${esc(s.text)}</p>` : ''}${s.code ? `
                  <div class="vcode"><pre><code>${esc(s.code)}</code></pre><button class="vcode__copy" type="button" data-copy="${esc(s.code)}">Copy</button></div>` : ''}</li>`).join('')}
              </ol>
              ${o.link.url ? `<a class="btn btn--line btn--line-haz vhost__dl" href="${esc(o.link.url)}" target="_blank" rel="noopener">${esc(o.link.label)} <span aria-hidden="true">&#8595;</span></a>` : ''}
            </article>`).join('')}
          </div>
          ${h.commands.length || h.flags.length ? `
          <div class="vhost__ref">
            ${h.commands.length ? `<div><h3>Console commands</h3><p class="vhost__small">Type these into the server window while it runs.</p>${kv(h.commands, 'vhost__kv--cmd')}</div>` : ''}
            ${h.flags.length ? `<div><h3>Options</h3><p class="vhost__small">Add them after <code>python3 server.py</code>.</p>${kv(h.flags, 'vhost__kv--flag')}</div>` : ''}
          </div>` : ''}
          ${h.faq.length ? `
          <div class="vhost__faq"><h3>Common questions</h3>${h.faq.map(f => `
            <details><summary>${esc(f.q)}</summary><p>${esc(f.a)}</p></details>`).join('')}
          </div>` : ''}
        </section>`;
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('.vcode__copy');
    if (!b) return;
    const done = ok => { b.textContent = ok ? 'Copied' : 'Select it and copy'; setTimeout(() => { b.textContent = 'Copy'; }, 1600); };
    if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(() => done(true), () => done(false));
    else done(false);
  });

  function galleryHTML(list) {
    return list.map((g, i) => `
      <button class="vgal__item" type="button" data-shot="${i}">
        <img src="${esc(g.src)}" alt="${esc(g.caption)}" loading="lazy" decoding="async" width="1600" height="900">
        <span class="vgal__cap">${esc(g.caption)}</span>
      </button>`).join('');
  }

  /* ---------- Screenshot viewer ---------- */
  let shots = [];
  let shotAt = 0;
  const lb = document.getElementById('lightbox');
  function showShot(i) {
    if (!shots.length) return;
    shotAt = (i + shots.length) % shots.length;
    document.getElementById('lightbox-img').src = shots[shotAt].src;
    document.getElementById('lightbox-img').alt = shots[shotAt].caption;
    document.getElementById('lightbox-cap').textContent = shots[shotAt].caption;
    lb.hidden = false;
    document.body.classList.add('no-scroll');
  }
  function closeShot() { lb.hidden = true; document.body.classList.remove('no-scroll'); }
  if (lb) {
    lb.querySelector('.lightbox__close').addEventListener('click', closeShot);
    lb.querySelector('.lightbox__prev').addEventListener('click', () => showShot(shotAt - 1));
    lb.querySelector('.lightbox__next').addEventListener('click', () => showShot(shotAt + 1));
    lb.addEventListener('click', e => { if (e.target === lb) closeShot(); });
    document.addEventListener('keydown', e => {
      if (lb.hidden) return;
      if (e.key === 'Escape') closeShot();
      if (e.key === 'ArrowLeft') showShot(shotAt - 1);
      if (e.key === 'ArrowRight') showShot(shotAt + 1);
    });
    document.addEventListener('click', e => {
      const b = e.target.closest('[data-shot]');
      if (b) showShot(+b.dataset.shot);
    });
  }

  function missingHTML() {
    return `
      <section class="wrap missing">
        <p class="eyebrow">Page not found</p>
        <h1>Nothing through this portal.</h1>
        <p>There's no page at <code>/${esc(route)}</code>. It may have moved, or it isn't out yet.</p>
        <a class="btn btn--solid" href="/">Back to Vortal</a>
      </section>`;
  }

  /* ---------- Contact ---------- */
  const topics = () => ['General', ...live.map(p => p.name), ...soon.map(p => p.name), 'Partnership', 'Bug report'];

  function contactFormHTML(chosen) {
    const all = topics();
    const pick = all.includes(chosen) ? chosen : 'General';
    return `
      <form class="cform" id="contact-form" novalidate>
        <div class="cform__row">
          <label class="cfield"><span>Your name</span>
            <input name="name" autocomplete="name" maxlength="80" required>
            <em class="cfield__error" data-for="name" hidden></em></label>
          <label class="cfield"><span>Your email</span>
            <input name="email" type="email" autocomplete="email" maxlength="200" required>
            <em class="cfield__error" data-for="email" hidden></em></label>
        </div>
        <label class="cfield"><span>What it's about</span>
          <select name="topic">${all.map(t => `<option${t === pick ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></label>
        <label class="cfield"><span>Message</span>
          <textarea name="message" rows="7" maxlength="5000" required></textarea>
          <em class="cfield__error" data-for="message" hidden></em>
          <small class="cfield__count">0 / 5000</small></label>
        <label class="cform__trap" aria-hidden="true">Leave this empty <input name="website" tabindex="-1" autocomplete="off"></label>
        <p class="cform__status" role="alert" hidden></p>
        <button class="btn btn--solid" type="submit">Send message</button>
      </form>`;
  }

  function contactPageHTML() {
    return `
      <section class="contact">
        <div class="wrap contact__grid">
          <div class="contact__intro">
            <nav class="crumbs" aria-label="Breadcrumb">
              <a href="/">Vortal</a><span aria-hidden="true">/</span><span aria-current="page">Contact</span>
            </nav>
            <h1 class="product__name">Get in touch</h1>
            <p class="product__lede">A question about something we make, a bug to report, or an idea for Vortal? Send a message and it goes straight to our inbox.</p>
            <dl class="contact__tips">
              <div><dt>Bug reports</dt><dd>Say what you did, what you expected, and what happened instead.</dd></div>
              <div><dt>Partnerships</dt><dd>Tell us about your server or project and what you have in mind.</dd></div>
              <div><dt>Replies</dt><dd>We answer at the email address you give, usually within a couple of days.</dd></div>
            </dl>
          </div>
          <div class="contact__card" id="contact-card">${contactFormHTML(new URLSearchParams(location.search).get('topic'))}</div>
        </div>
      </section>`;
  }

  const CONTACT_ERRORS = {
    fast: 'That was quick! Wait a moment, then press Send again.',
    limit: "You've sent several messages in the last hour. Please try again later.",
    origin: 'Please send the form from vortal.space.',
  };

  function wireContact() {
    const card = document.getElementById('contact-card');
    if (!card) return;
    const started = Date.now();
    const form = card.querySelector('form');
    const field = n => form.elements.namedItem(n);
    const count = form.querySelector('.cfield__count');
    field('message').addEventListener('input', () => { count.textContent = `${field('message').value.length} / 5000`; });
    const fieldError = (name, text) => {
      const el = form.querySelector(`[data-for="${name}"]`);
      el.textContent = text || '';
      el.hidden = !text;
      field(name).setAttribute('aria-invalid', text ? 'true' : 'false');
    };
    const status = text => { const el = form.querySelector('.cform__status'); el.textContent = text || ''; el.hidden = !text; };

    form.addEventListener('submit', async e => {
      e.preventDefault();
      const data = {
        name: field('name').value.trim(), email: field('email').value.trim(), topic: field('topic').value,
        message: field('message').value.trim(), website: field('website').value, started,
      };
      const problems = {
        name: data.name ? '' : 'Add your name.',
        email: /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/.test(data.email) ? '' : 'Add an email address we can reply to.',
        message: data.message.length >= 10 ? '' : 'Write a little more: at least 10 characters.',
      };
      Object.entries(problems).forEach(([k, v]) => fieldError(k, v));
      status('');
      const first = Object.keys(problems).find(k => problems[k]);
      if (first) { field(first).focus(); return; }

      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      btn.textContent = 'Sending…';
      try {
        const res = await fetch('/api/contact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        const out = await res.json().catch(() => ({}));
        if (res.ok) {
          card.innerHTML = `
            <div class="csent" tabindex="-1">
              <span class="csent__mark" aria-hidden="true"></span>
              <h2>Message sent</h2>
              <p>Thanks, ${esc(data.name)}. We'll reply to <b>${esc(data.email)}</b>.</p>
              <button class="btn btn--line" type="button">Send another message</button>
            </div>`;
          card.querySelector('.csent').focus();
          card.querySelector('button').addEventListener('click', () => { card.innerHTML = contactFormHTML(data.topic); wireContact(); });
          return;
        }
        const byField = { name: 'Add your name.', email: "That email address doesn't look right.", message: 'Write a little more: at least 10 characters.' };
        if (byField[out.error]) { fieldError(out.error, byField[out.error]); field(out.error).focus(); }
        else status(CONTACT_ERRORS[out.error] || 'Something went wrong on our side. Please try again in a minute.');
      } catch {
        status("Couldn't send. Check your connection and try again.");
      } finally {
        if (btn.isConnected) { btn.disabled = false; btn.textContent = 'Send message'; }
      }
    });
  }

  /* ---------- Render the page for this address ---------- */
  if (route) {
    document.documentElement.dataset.route = 'page';
    const page = document.getElementById('page');
    const desc = document.querySelector('meta[name="description"]');
    if (route === 'community' && window.VortalCommunity) {
      document.title = 'Community · Vortal';
      if (desc) desc.setAttribute('content', 'News from Vortal and the live Volatile chat.');
      document.querySelectorAll('.nav__link[href="/community"]').forEach(a => a.setAttribute('aria-current', 'page'));
      window.VortalCommunity.page(page);
    } else if (route === 'account' && window.VortalAccount) {
      document.title = 'Account · Vortal';
      if (desc) desc.setAttribute('content', 'Your Vortal account: sign in, create an account, manage it.');
      window.VortalAccount.render(page);
    } else if (route === 'contact') {
      page.innerHTML = contactPageHTML();
      document.title = 'Contact · Vortal';
      if (desc) desc.setAttribute('content', 'Send Vortal a message: questions, bug reports, partnerships.');
      document.querySelectorAll('.nav__link[href="/contact"]').forEach(a => a.setAttribute('aria-current', 'page'));
      wireContact();
    } else {
      page.innerHTML = current ? productPageHTML(current) : missingHTML();
      if (current) shots = current.gallery;
      wireVideos(page);
      const com = page.querySelector('#community');
      if (com && window.VortalCommunity) window.VortalCommunity.mount(com, { heading: 'News &amp; chat' });
      // /volatile#server: jump to the hosting guide once it's on the page
      if (current && location.hash.length > 1) {
        const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
        if (target && target.tagName === 'DETAILS') target.open = true;
        if (target) requestAnimationFrame(() => target.scrollIntoView());
      }
      document.title = current ? `${current.name} · Vortal` : 'Page not found · Vortal';
      if (current && current.summary && desc) desc.setAttribute('content', current.summary);
    }
  } else {
    const star = listed.find(p => p.spotlight) || null;
    if (star) {
      shots = star.gallery.length ? star.gallery : [{ src: star.image, caption: star.caption }];
      const badges = [star.kind, ...(star.spec ? star.spec.split('·').map(s => s.trim()).filter(Boolean) : [])];
      document.getElementById('vhero-badges').innerHTML = badges.map((b, i) => `<span class="${i === 0 ? 'vbadge vbadge--hot' : 'vbadge'}">${esc(b)}</span>`).join('');
      const dl = [star.link, ...star.more].filter(l => V.safeUrl(l.url) && !l.minor);   // minor links (e.g. the server) stay on the product page
      document.getElementById('vhero-cta').innerHTML = downloadsHTML(dl, true) +
        `<a class="btn btn--line btn--line-haz" href="${href(star)}">Details</a>`;
      document.getElementById('vgal-grid').innerHTML = galleryHTML(shots);
      const watch = document.getElementById('watch');
      if (star.videos.length) {
        document.getElementById('vvid-grid').innerHTML = videosHTML(star.videos);
        wireVideos(watch);
      } else {
        watch.hidden = true;
      }
      // hero slideshow
      const img = document.getElementById('vshow-img');
      const cap = document.getElementById('vshow-cap');
      const dots = document.getElementById('vshow-dots');
      let at = 0;
      let timer = 0;
      dots.innerHTML = shots.map((g, i) => `<button class="vshow__dot" type="button" role="tab" aria-label="${esc(g.caption)}" data-i="${i}"></button>`).join('');
      const go = i => {
        at = (i + shots.length) % shots.length;
        img.classList.add('is-fading');
        setTimeout(() => {
          img.src = shots[at].src;
          img.alt = shots[at].caption;
          cap.textContent = shots[at].caption;
          img.classList.remove('is-fading');
        }, reduceMotion ? 0 : 280);
        dots.querySelectorAll('.vshow__dot').forEach((d, k) => d.setAttribute('aria-selected', String(k === at)));
      };
      const auto = () => { clearInterval(timer); if (!reduceMotion) timer = setInterval(() => go(at + 1), 5200); };
      dots.addEventListener('click', e => { const d = e.target.closest('[data-i]'); if (d) { go(+d.dataset.i); auto(); } });
      img.addEventListener('click', () => showShot(at));
      img.style.cursor = 'zoom-in';
      go(0);
      auto();
      // preload the rest so the slideshow never flashes
      shots.slice(1).forEach(g => { const pre = new Image(); pre.src = g.src; });
    } else {
      document.getElementById('top').hidden = true;
      document.getElementById('inside').hidden = true;
      document.getElementById('watch').hidden = true;
    }
    // the spotlight game first, then everything else
    live.sort((a, b) => (b.spotlight === true) - (a.spotlight === true));
    document.getElementById('release-list').innerHTML = live.length
      ? live.map(cardHTML).join('')
      : '<p class="empty">Nothing released yet. Check back soon.</p>';
    document.getElementById('releases-meta').textContent = `${live.length} out now · ${soon.length} coming soon`;

    if (soon.length) {
      document.getElementById('soon-list').innerHTML = soon.map(soonHTML).join('');
      document.getElementById('soon-meta').textContent = `${soon.length} in the works`;
    } else {
      document.getElementById('soon').hidden = true;
    }

    // What we make: one entry per category, with what's out and what's next.
    const link = p => `<a href="${href(p)}">${esc(p.name)}</a>`;
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
  }

  document.getElementById('foot-links').innerHTML =
    listed.map(p => `<li><a href="${href(p)}"${p === current ? ' aria-current="page"' : ''}>${esc(p.name)}</a></li>`).join('') +
    `<li><a href="/contact"${route === 'contact' ? ' aria-current="page"' : ''}>Contact</a></li>` +
    `<li><a href="/community"${route === 'community' ? ' aria-current="page"' : ''}>Community</a></li>` +
    `<li><a href="/account"${route === 'account' ? ' aria-current="page"' : ''}>Account</a></li>`;

  /* ---------- Products dropdown ---------- */
  const menuBtn = document.getElementById('menu-btn');
  const menu = document.getElementById('menu-products');
  const menuGroup = (title, list) => list.length ? `
    <div class="menu__group">
      <p class="menu__label">${title}</p>
      ${list.map(p => `
        <a class="menu__item" href="${href(p)}" style="--accent:${V.shadeHex(p.shade)}"${p === current ? ' aria-current="page"' : ''}>
          <span class="px menu__icon" data-icon="${cat(p).icon}"></span>
          <span class="menu__text">
            <span class="menu__name">${esc(p.name)}</span>
            <span class="menu__cat">${esc(p.kind || cat(p).label)}</span>
          </span>
        </a>`).join('')}
    </div>` : '';
  menu.innerHTML = (menuGroup('Out now', live) + menuGroup('Coming soon', soon)) ||
    '<p class="menu__label">No products yet</p>';

  const setMenu = open => { menu.hidden = !open; menuBtn.setAttribute('aria-expanded', String(open)); };
  menuBtn.addEventListener('click', () => setMenu(menu.hidden));
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

  /* ---------- Hero portal (home only) ---------- */
  const portal = document.getElementById('portal');
  if (portal && !route) {
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

  /* ---------- Scroll reveal ----------
     Blocks below the fold rise into place as they scroll into view. Anything
     already on screen is left alone, so the first view never waits on this. */
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
    }, { rootMargin: '0px 0px -6% 0px' });
    const fold = innerHeight * 0.95;
    document.querySelectorAll('.section-head, .pgrid > .pcard, .soon__list > li, .disc, .next__inner, .features > div, .callout, .product__soon')
      .forEach(el => {
        if (el.getBoundingClientRect().top < fold) return;
        const i = [...el.parentElement.children].indexOf(el);
        el.style.setProperty('--delay', `${Math.min(i, 5) * 70}ms`);
        el.classList.add('reveal');
        io.observe(el);
      });
  }
  mountCountdowns(document);

  /* ---------- The last 24 hours before 1.0: downloads pause ----------
     Every Volatile download link (they all point at the volatile-download
     branch) is switched off with a note, and back on at the launch, when the
     page reloads to show the official release. */
  const DL = 'a[href*="/volatile-download/"]';
  function applyDownloadPause() {
    const paused = V.downloadsPaused();
    document.querySelectorAll(DL + ', a[data-paused-href]').forEach(a => {
      if (paused && !a.dataset.pausedHref) {
        a.dataset.pausedHref = a.getAttribute('href');
        a.removeAttribute('href');
        a.setAttribute('aria-disabled', 'true');
        a.classList.add('is-paused');
        a.title = 'Downloads are back when Volatile 1.0 comes out';
      } else if (!paused && a.dataset.pausedHref) {
        a.setAttribute('href', a.dataset.pausedHref);
        delete a.dataset.pausedHref;
        a.removeAttribute('aria-disabled');
        a.classList.remove('is-paused');
        a.removeAttribute('title');
      }
    });
    document.querySelectorAll('.dl-paused').forEach(n => n.remove());
    if (!paused) return;
    const when = new Date(RELEASE).toLocaleString(undefined, { weekday: 'long', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });
    const note = full => {
      const p = document.createElement('p');
      p.className = full ? 'dl-paused' : 'dl-paused dl-paused--short';
      if (full) p.setAttribute('role', 'status');
      p.innerHTML = full
        ? `<b>Downloads are paused for the final 24 hours.</b> They're back ${esc(when)} with the official release of Volatile 1.0.`
        : `<b>Paused until launch</b> · back ${esc(when)}`;
      return p;
    };
    // the full note above the first group of download buttons, a short one above the rest
    const groups = new Set();
    document.querySelectorAll('a[data-paused-href]').forEach(a => groups.add(a.closest('.dl') || a.parentElement));
    [...groups].forEach((g, i) => g.parentElement.insertBefore(note(i === 0), g));
  }
  applyDownloadPause();
  const untilFreeze = V.FREEZE - Date.now();
  const untilRelease = RELEASE - Date.now();
  if (untilFreeze > 0 && untilFreeze < 2147483647) setTimeout(applyDownloadPause, untilFreeze + 500);
  // at the launch, reload once so the official downloads and copy show up
  if (untilRelease > 0 && untilRelease < 2147483647) setTimeout(() => location.reload(), untilRelease + 1500);
})();
