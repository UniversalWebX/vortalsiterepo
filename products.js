/*
  Vortal products. The Released, Coming soon, What we make, and Products menu
  sections are all built from this list. Edit it, save, and re-deploy.

  Fields:
    id        Short name used in links, e.g. "donutduck" (lowercase, no spaces)
    name      Display name
    category  games | minecraft | gd | windhawk | discord | devices
    status    released | soon | hidden
    shade     violet | orchid | rose | plum | lavender | iris | periwinkle
    spec      One-line specs (optional)
    summary   One or two sentences
    features  List of { "label": "...", "text": "..." }. Put → between words to show steps.
    note      Extra line (optional). Wrap a key in backticks for a keycap: `K`
    link      { "label": "...", "url": "https://..." }. Leave url empty for no button.
    visual    icon | claims | board
*/
window.VORTAL_PRODUCTS = [
  {
    "id": "cis-factions",
    "name": "CIS Factions",
    "category": "minecraft",
    "status": "released",
    "shade": "violet",
    "spec": "NeoForge 21.1.x · Minecraft 1.21.1",
    "summary": "Territory, government, and warfare for the Create Industries SMP. Found a faction, claim land, run a government, go to war — and check papers at the border.",
    "features": [
      { "label": "Territory", "text": "A 3D isometric map of the real terrain, showing who owns what." },
      { "label": "Government", "text": "Eleven rank tiers and 27 permissions to hand out between them." },
      { "label": "War", "text": "Justify → Declare → Siege → Conquer" },
      { "label": "Economy", "text": "Faction treasuries, player wallets, and payroll." },
      { "label": "Papers", "text": "ID cards, passports, visas, and border control." },
      { "label": "Jobs", "text": "Paid posts and work stations, plus seven Create job types with Create 6.x." }
    ],
    "note": "Everything opens from one control panel: press `K`. Permissions are checked on the server, players don't need the mod installed, and all data is readable JSON with around 50 server settings.",
    "link": { "label": "Get it on CurseForge", "url": "https://www.curseforge.com/minecraft/mc-mods/cis-factions" },
    "visual": "claims"
  },
  {
    "id": "monopoline",
    "name": "Monopoline",
    "category": "games",
    "status": "released",
    "shade": "orchid",
    "spec": "Browser · installs to your home screen · plays offline",
    "summary": "Runs every system of a property game except the board itself. Bring any board, or none at all — Monopoline keeps the bank, the deeds, rent, cards, and jail.",
    "features": [
      { "label": "The bank", "text": "Take a loan. It charges 10% interest every time you pass GO." },
      { "label": "Job draft", "text": "Pick a job that pays on every GO and bends one rule your way. It levels up on laps 3 and 6." },
      { "label": "Alliances", "text": "Half rent between allies, a tenth of each other's takings, and a shared win. Breaking one costs you." },
      { "label": "Live table", "text": "Everyone watching sees the table update live." },
      { "label": "House rules", "text": "Set the rules and modes before the first roll." },
      { "label": "Ledger", "text": "Every payment logged, with stats and final standings." }
    ],
    "note": "New to it? A seven-step tour walks you through the real table, not a slideshow.",
    "link": { "label": "Play Monopoline", "url": "https://monopoline.onrender.com/" },
    "visual": "board"
  },
  {
    "id": "donutduck",
    "name": "DonutDuck",
    "category": "discord",
    "status": "soon",
    "shade": "rose",
    "spec": "",
    "summary": "A Discord bot from Vortal. Full details at launch.",
    "features": [],
    "note": "",
    "link": { "label": "", "url": "" },
    "visual": "icon"
  },
  {
    "id": "windhawk-mod",
    "name": "Windhawk mod",
    "category": "windhawk",
    "status": "soon",
    "shade": "periwinkle",
    "spec": "",
    "summary": "A Windows customization mod built for Windhawk. Name and details at launch.",
    "features": [],
    "note": "",
    "link": { "label": "", "url": "" },
    "visual": "icon"
  }
];
