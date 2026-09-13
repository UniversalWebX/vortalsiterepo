/*
  Shared data helpers. There is no server: the product list lives in
  products.js, and this file cleans it up and supplies the lookup tables.
*/
(() => {
  const SHADES = {
    violet:     { label: 'Violet',     hex: '#A259FF' },
    orchid:     { label: 'Orchid',     hex: '#E05BC4' },
    rose:       { label: 'Rose',       hex: '#FF6FAE' },
    plum:       { label: 'Plum',       hex: '#C77DDB' },
    lavender:   { label: 'Lavender',   hex: '#C9A7FF' },
    iris:       { label: 'Iris',       hex: '#8B7BFF' },
    periwinkle: { label: 'Periwinkle', hex: '#7B9BFF' },
  };

  const CATEGORIES = {
    games:     { label: 'Web game',          group: 'Games',              icon: 'dice',   shade: 'orchid',     blurb: 'Original games and the systems that run them, playable in a browser tab or at the table.' },
    minecraft: { label: 'Minecraft mod',     group: 'Minecraft mods',     icon: 'block',  shade: 'violet',     blurb: 'Big server systems for NeoForge: land, law, money, and war.' },
    gd:        { label: 'Geometry Dash mod', group: 'Geometry Dash mods', icon: 'cube',   shade: 'lavender',   blurb: 'Mods for Geometry Dash players and level creators.' },
    windhawk:  { label: 'Windhawk mod',      group: 'Windhawk mods',      icon: 'window', shade: 'periwinkle', blurb: 'Mods that customize Windows and its programs, built for Windhawk.' },
    discord:   { label: 'Discord bot',       group: 'Discord bots',       icon: 'bot',    shade: 'iris',       blurb: 'Bots that live in your Discord server.' },
    devices:   { label: 'Physical device',   group: 'Physical devices',   icon: 'chip',   shade: 'plum',       blurb: 'Hardware you can hold, built on the same bench as the software.' },
  };

  const STATUSES = { released: 'Out now', soon: 'Coming soon', hidden: 'Hidden' };
  const VISUALS = { icon: 'Category icon', claims: 'Claims map', board: 'Board loop', dots: 'Dots board', giveaway: 'Giveaway message' };

  const ICONS = {
    dice:   ['#########', '#.......#', '#.#...#.#', '#.......#', '#...#...#', '#.......#', '#.#...#.#', '#.......#', '#########'],
    block:  ['#########', '#########', '##.##.###', '#.......#', '#..+....#', '#.....+.#', '#.+.....#', '#....+..#', '#########'],
    cube:   ['#########', '#.......#', '#.##.##.#', '#.##.##.#', '#.......#', '#.......#', '#.#####.#', '#.......#', '#########'],
    window: ['####.####', '####.####', '####.####', '####.####', '.........', '####.####', '####.####', '####.####', '####.####'],
    bot:    ['....#....', '....#....', '.#######.', '#.......#', '#.##.##.#', '#.......#', '#..###..#', '.#######.', '..#...#..'],
    chip:   ['..#.#.#..', '.#######.', '##.....##', '.#.###.#.', '##.###.##', '.#.###.#.', '##.....##', '.#######.', '..#.#.#..'],
  };

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // Full http(s) links, or files on this site like /files/guide.pdf (but not //other-site).
  const safeUrl = u => (/^https?:\/\//i.test(u || '') || /^\/(?!\/)/.test(u || '') ? u : '');
  const shadeHex = k => (SHADES[k] || SHADES.violet).hex;
  const slug = name => String(name).toLowerCase().normalize('NFKD').replace(/[^\w\s-]/g, '')
    .trim().replace(/[\s_]+/g, '-').replace(/-+/g, '-') || 'product';

  // Fill in anything missing so a typo in products.js never breaks the page.
  function normalize(p = {}) {
    const str = v => (typeof v === 'string' ? v : '');
    const link = p.link || {};
    return {
      id: str(p.id) || slug(str(p.name)),
      name: str(p.name),
      category: CATEGORIES[p.category] ? p.category : 'games',
      status: STATUSES[p.status] ? p.status : 'hidden',
      shade: SHADES[p.shade] ? p.shade : 'violet',
      spec: str(p.spec),
      summary: str(p.summary),
      features: Array.isArray(p.features) ? p.features.map(f => ({ label: str(f && f.label), text: str(f && f.text) })) : [],
      note: str(p.note),
      link: { label: str(link.label), url: str(link.url) },
      source: str(p.source),
      guide: { label: str((p.guide || {}).label), url: str((p.guide || {}).url) },
      visual: VISUALS[p.visual] ? p.visual : 'icon',
    };
  }

  const products = () => (Array.isArray(window.VORTAL_PRODUCTS) ? window.VORTAL_PRODUCTS : []).map(normalize);

  function iconSVG(name) {
    const rows = ICONS[name] || ICONS.dice;
    let rects = '';
    rows.forEach((line, y) => [...line].forEach((ch, x) => {
      if (ch === '#') rects += `<rect x="${x}" y="${y}" width="1" height="1"/>`;
      if (ch === '+') rects += `<rect x="${x}" y="${y}" width="1" height="1" opacity=".45"/>`;
    }));
    return `<svg viewBox="0 0 9 9" shape-rendering="crispEdges" fill="currentColor" aria-hidden="true">${rects}</svg>`;
  }
  const paintIcons = (root = document) => root.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = iconSVG(el.dataset.icon); });

  window.Vortal = { SHADES, CATEGORIES, STATUSES, esc, safeUrl, shadeHex, products, paintIcons };
})();
