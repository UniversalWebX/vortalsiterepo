/*
  Vortal products. The Released, Coming soon, What we make, and Products menu
  sections are all built from this list. Edit it, save, and re-deploy.

  Fields:
    id        The page address: "donutduck" becomes vortal.space/donutduck (lowercase, no spaces)
    name      Display name
    category  games | minecraft | gd | windhawk | discord | devices
    status    released | soon | hidden
    shade     violet | orchid | rose | plum | lavender | iris | periwinkle
    spec      One-line specs (optional)
    summary   One or two sentences
    features  List of { "label": "...", "text": "..." }. Put → between words to show steps.
    note      Extra line (optional). Wrap a key in backticks for a keycap: `K`
    link      { "label": "...", "url": "https://..." }. Leave url empty for no button.
    more      More download buttons, e.g. other platforms: [{ "label": "...", "url": "..." }] (optional)
    videos    YouTube videos for the product page: [{ "id": "11-char id", "title": "...", "premiere": "ISO time" }] (optional)
    launch    Fields that replace these ones once Volatile 1.0 is out (Oct 1, 5:30 PM Pacific), e.g. the
              official download labels; "drop_features" lists feature labels to hide then (optional)
              Add "minor": true to keep a button off the home-page hero (it still shows on the product page).
    hosting   A "host a server" guide on the product page (optional): { title, lede, options: [{ name, tag, steps: [{ text, code }], link }],
              commands: [[command, what it does]], flags: [[flag, what it does]], faq: [{ q, a }] }. Linked as /<id>#server.
    source    Link to the code, e.g. a GitHub repo (optional). Adds a "View source" button.
    guide     { "label": "...", "url": "..." } for a manual or tutorial (optional). Put the file in
              site/files/ and link it as "/files/name.pdf".
    visual    icon | claims | board | dots | giveaway | shot
    kind      Badge text instead of the category's, e.g. "PC game" (optional)
    image     For visual "shot": a screenshot in site/files/, e.g. "/files/volatile.jpg"
    gallery   More screenshots for the product page: [{ "src": "/files/...", "caption": "..." }] (optional)
    spotlight true for the one product the home page is built around (optional)
    caption   For visual "shot": the line under the screenshot (optional)
*/
window.VORTAL_PRODUCTS = [
  {
    "id": "volatile",
    "name": "Volatile",
    "category": "games",
    "kind": "PC, Mac & Android",
    "status": "released",
    "shade": "plum",
    "spec": "Update 1 Beta · Windows · Mac · Android · crossplay co-op for up to 8",
    "summary": "A co-op factory builder in a toxic wasteland. Humanity is gone, production isn't: scavenge, build drills, smelters and conveyor lines, and push the last working machine through five directives.",
    "features": [
      { "label": "Automate", "text": "Drill → Smelt → Construct → Store" },
      { "label": "Worker bots", "text": "Build robots and order them to mine, feed the Terminal, refuel generators, or stand guard." },
      { "label": "A 10 km wasteland", "text": "Ruined cities and meltdown sites near home, richer ore and meaner mutants the further you travel." },
      { "label": "Survive", "text": "Toxic storms, radiation, mutant packs, and two bosses: the Matriarch and the Warden Mk.IX." },
      { "label": "Crossplay co-op", "text": "Up to 8 players on PC, Mac and Android together, with join codes, proximity voice chat, emotes, and shared worlds." },
      { "label": "Update 1 Beta", "text": "Belts pathfind around trees and tunnel through hills, a built-in wiki (F1), icons for every building, and voice chat that no longer lags." },
      { "label": "Dedicated servers", "text": "Keep a world online 24/7 on a spare PC or a Linux VPS with server.py, so friends on other networks can join any time." },
      { "label": "Always up to date", "text": "Updates download in the background and install themselves, on every platform." },
      { "label": "Skip the night", "text": "Sleep through the dark in a few seconds; in co-op, everyone votes." },
      { "label": "Runs on laptops", "text": "A big performance pass: about a third fewer draw calls, cheaper shadows and faster loading, tuned on integrated graphics." }
    ],
    "note": "Windows: unzip and run Volatile.exe. Mac: unzip, move Volatile to Applications, then right-click it and choose Open. We're not on the Mac App Store yet, so macOS flags Volatile as coming from an unidentified developer; if it's still blocked, open System Settings, then Privacy & Security, and click Open Anyway. The first launch takes a minute or two while macOS prepares the graphics. Android: open the APK on your phone and allow the install. Volatile updates itself automatically. To host a world that stays online, run server.py (it's in the Windows download, and the Linux server download is made for a VPS), then share the join code it prints. Stuck or found a bug? Use Support in the game's menu.",
    "link": { "label": "Download beta for Windows (37 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-win64.zip", "platform": "windows" },
    "more": [
      { "label": "Download beta for Mac (59 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-macOS.zip", "platform": "mac" },
      { "label": "Download beta for Android (26 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-android.apk", "platform": "android" },
      { "label": "Beta dedicated server for Linux (28 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-linux-server.zip", "minor": true }
    ],
    "videos": [
      { "id": "q5fXmP55Ewk", "title": "Volatile: official trailer", "premiere": "2026-09-28T18:30:00-07:00" },
      { "id": "e6bSVCToKPc", "title": "Volatile 1.0 gameplay test" }
    ],
    "launch": {
      "kind": "PC, Mac, Android & Chromebook",
      "spec": "1.0 · Windows · Mac · Android · Chromebook · crossplay co-op for up to 8",
      "howtos": [
        { "id": "chromebook", "title": "Playing on a Chromebook", "steps": [
          "Turn on Linux: Settings, then About ChromeOS, then Developers, then Linux development environment, then Turn on.",
          "In the same Linux settings, open Develop Android apps and turn on Enable ADB debugging. Your Chromebook restarts.",
          "Download Volatile for Chromebook above, then move Volatile-android.apk into Linux files in the Files app.",
          "Open the Terminal app and run these three lines, accepting the debugging prompt when it appears: `sudo apt install -y adb`, then `adb connect arc`, then `adb install Volatile-android.apk`",
          "Volatile is now in your launcher. It plays with keyboard and mouse; on a touchscreen Chromebook, Settings, then Game, then Controls switches to touch.",
          "School and work Chromebooks usually block Linux and debugging. If yours does, ask whoever manages it."
        ] }
      ],
      "features": [
        { "label": "Automate", "text": "Drill → Smelt → Construct → Store" },
        { "label": "Worker bots", "text": "Build robots and order them to mine, feed the Terminal, refuel generators, or stand guard." },
        { "label": "A 10 km wasteland", "text": "Ruined cities and meltdown sites near home, richer ore and meaner mutants the further you travel." },
        { "label": "Survive", "text": "Toxic storms, radiation, mutant packs, and two bosses: the Matriarch and the Warden Mk.IX." },
        { "label": "Crossplay co-op", "text": "Up to 8 players on PC, Mac and Android together, with join codes, proximity voice chat, emotes, and shared worlds." },
        { "label": "Easier automation", "text": "Machines pick their own recipe from what arrives, Belt Filters split outputs, and belts pathfind around trees and tunnel through hills." },
        { "label": "Vortal accounts", "text": "One free account for online play: your name can't be faked, and your items follow you between devices. Solo needs none." },
        { "label": "Fair play", "text": "The host checks every build, delivery and trade against what you really have, and moderators can kick, mute and ban." },
        { "label": "Public servers", "text": "Find public games and dedicated servers right in Join Co-op, or list your own." },
        { "label": "Dedicated servers", "text": "Keep a world online 24/7 on a spare PC or a Linux VPS with server.py, so friends on other networks can join any time." },
        { "label": "Always up to date", "text": "Updates download in the background and install themselves, on every platform." },
        { "label": "Skip the night", "text": "Sleep through the dark in a few seconds; in co-op, everyone votes." },
        { "label": "Runs on laptops", "text": "A big performance pass: about a third fewer draw calls, cheaper shadows and faster loading, tuned on integrated graphics." }
      ],
      "hosting_add": {
        "flags": [["--public", "list it on the public server list in Join Co-op"]],
        "faq": [
          { "q": "How do people find my server?", "a": "Start it with --public and it shows up under Public servers in everyone's Join Co-op. Otherwise share the join code it prints. Players need a free Vortal account to play online (vortal.space/account)." },
          { "q": "How do I moderate it?", "a": "Type ban, kick, mute, warn or announce in the server window (players, say and status too). World bans are saved with the world." }
        ]
      },
      "link": { "label": "Download for Windows (37 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-win64.zip", "platform": "windows" },
      "more": [
        { "label": "Download for Mac (59 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-macOS.zip", "platform": "mac" },
        { "label": "Download for Android (54 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-android.apk", "platform": "android" },
        { "label": "Download for Chromebook (54 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-android.apk", "platform": "chromebook", "hint": "Installs as an Android app: see Playing on a Chromebook further down this page for the steps." },
        { "label": "Dedicated server for Linux (28 MB)", "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-linux-server.zip", "minor": true }
      ]
    },
    "visual": "shot",
    "image": "/files/volatile-factory.jpg",
    "spotlight": true,
    "gallery": [
      { "src": "/files/volatile-factory.jpg", "caption": "The first factory: drills, smelter and constructor on salvaged power" },
      { "src": "/files/volatile-storm.jpg", "caption": "A toxic storm front rolls in over the base" },
      { "src": "/files/volatile-night.jpg", "caption": "Night shift: flood lamps, sliding doors and the Terminal's glow" },
      { "src": "/files/volatile-bots.jpg", "caption": "Worker bots, each in its own paint job, waiting for a program" },
      { "src": "/files/volatile-vehicles.jpg", "caption": "Rovers and haulers, driven or on autopilot" },
      { "src": "/files/volatile-boss.jpg", "caption": "The Matriarch and the Warden Mk.IX" },
      { "src": "/files/volatile-tablet.jpg", "caption": "The field datapad: map, story log and a built-in wiki" }
    ],
    "caption": "The first factory: drill → smelter → constructor, powered from the Directive Terminal",
    "hosting": {
      "title": "Host a server",
      "lede": "Keep a Volatile world online around the clock, so friends can join from anywhere, even when you're not playing. The server runs the game without a screen and all 8 player slots are for people who join. It restarts itself if it crashes, saves every 5 minutes, and updates itself when a new version comes out (warning everyone a minute before).",
      "options": [
        {
          "name": "On a Windows PC",
          "tag": "Easiest",
          "steps": [
            {
              "text": "Download Volatile for Windows and unzip it."
            },
            {
              "text": "Double-click Start server.bat in the game folder. With Python 3 installed you get auto-restart, auto-update and a console; without it, a basic server still runs."
            },
            {
              "text": "It prints a join code. Send it to your friends: they open Join Co-op and paste it."
            },
            {
              "text": "If it says your router didn't open the port, forward UDP 7777 to this PC in your router's settings (or use a VPS instead)."
            }
          ],
          "link": {
            "label": "Download for Windows (37 MB)",
            "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-win64.zip"
          }
        },
        {
          "name": "On a Linux VPS",
          "tag": "Always online",
          "steps": [
            {
              "text": "Any small Linux VPS works: about 1 GB of memory is plenty, 2 GB for a busy 8-player world. Download the server and unzip it.",
              "code": "wget -O volatile.zip \"https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-linux-server.zip\"\nunzip volatile.zip -d volatile && cd volatile"
            },
            {
              "text": "Open the game's port in the firewall (UDP, not TCP). Many hosts also have a firewall in their control panel.",
              "code": "sudo ufw allow 7777/udp"
            },
            {
              "text": "Start it. The world is made the first time and loaded after that.",
              "code": "python3 server.py --world \"My world\" --name \"My server\""
            },
            {
              "text": "Keep it running after you log out (or run it inside screen or tmux):",
              "code": "nohup python3 server.py > server.log 2>&1 &"
            }
          ],
          "link": {
            "label": "Dedicated server for Linux (28 MB)",
            "url": "https://github.com/UniversalWebX/vortalsiterepo/raw/refs/heads/volatile-download/Volatile-linux-server.zip"
          }
        }
      ],
      "commands": [
        [
          "players",
          "who's online, their device and ping"
        ],
        [
          "say <message>",
          "a message to everyone in the game"
        ],
        [
          "kick <name>",
          "remove a player"
        ],
        [
          "save",
          "save the world now"
        ],
        [
          "status",
          "world, tier, version, join code and uptime"
        ],
        [
          "update",
          "check for a new version and install it"
        ],
        [
          "restart",
          "restart the server"
        ],
        [
          "stop",
          "save and shut down (Ctrl+C does the same)"
        ]
      ],
      "flags": [
        [
          "--world NAME",
          "which world to host (made if it doesn't exist)"
        ],
        [
          "--port 7777",
          "the UDP port"
        ],
        [
          "--seed 1234",
          "the map seed for a new world"
        ],
        [
          "--name NAME",
          "the server name shown in Join Co-op on the same network"
        ],
        [
          "--no-update",
          "don't update the game automatically"
        ]
      ],
      "faq": [
        {
          "q": "My friends can't connect.",
          "a": "Check the port is open for UDP (not TCP) both in the server's firewall and, at home, forwarded in your router. Everyone must be on the same version, which the game handles by updating itself. On the same Wi-Fi, the server shows up in Join Co-op without a code."
        },
        {
          "q": "Can I host from a Mac?",
          "a": "Yes: run python3 server.py --game /Applications/Volatile.app from a folder that has server.py (it's in the Windows and Linux downloads)."
        },
        {
          "q": "Where is the world saved?",
          "a": "In the game's normal save folder, under the world's name, so you can also open it in the game yourself. On Linux that's ~/.local/share/godot/app_userdata/Volatile/saves."
        },
        {
          "q": "Do I need Python?",
          "a": "Python 3.8 or newer, with nothing extra to install. Most Linux servers already have it; on Windows, get it from python.org."
        }
      ]
    }
  },
  {
    "id": "cisfactions",
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
    "link": { "label": "Play Monopoline", "url": "https://monopoline.vortal.space/" },
    "source": "https://github.com/UniversalWebX/vortalsiterepo/tree/main/monopoline",
    "visual": "board"
  },
  {
    "id": "nokhtebazi",
    "name": "Nokhtebazi",
    "category": "games",
    "status": "released",
    "shade": "iris",
    "spec": "Browser · online or on one device · English / فارسی",
    "summary": "Dots and Boxes, rebuilt. Join two dots, close a box to claim it and go again. Play friends online with a room link, pass one device around, or take on the computer.",
    "features": [
      { "label": "Rooms", "text": "Create a room and share the link. Up to six players join from any device, and latecomers watch." },
      { "label": "Four boards", "text": "Quick 5 × 5, Classic 8 × 8, Big 12 × 12, or the 25 × 25 Marathon." },
      { "label": "Fair play", "text": "The server checks every move, so turns and scores can't be faked." },
      { "label": "Live cursors", "text": "See where everyone is pointing as they play." },
      { "label": "One device", "text": "Play the computer, or pass the device between up to four players." },
      { "label": "Two languages", "text": "Switch between English and Persian any time." }
    ],
    "note": "The name is Persian: نقطه بازی, “the dots game”.",
    "link": { "label": "Play Nokhtebazi", "url": "https://nokhtebazi.vortal.space/" },
    "source": "https://github.com/UniversalWebX/vortalsiterepo/tree/main/nokhtebazi",
    "visual": "dots"
  },
  {
    "id": "donutduck",
    "name": "DonutDuck",
    "category": "discord",
    "status": "soon",
    "shade": "rose",
    "spec": "Discord bot · 157 commands · web dashboard",
    "summary": "An all-in-one Discord bot for DonutSMP communities: giveaways, tickets, staff checks, vouches, applications, and live player stats. It's one bot because they connect — a giveaway winner claims through a ticket, and whoever handles it earns a vouch.",
    "features": [
      { "label": "Giveaways", "text": "Winners claim through their own ticket, rerolls never repeat a winner, and two game modes: Split or Steal, and Double or Keep." },
      { "label": "Tickets", "text": "As many panels as you like, custom ticket types and forms, transcripts, and a reason on every ticket." },
      { "label": "Staff", "text": "One staff list for everything, activity checks that strike no-shows automatically, and legit votes." },
      { "label": "Player stats", "text": "DonutSMP balances, leaderboards, and auction prices, plus trackers that report changes every 12 hours." },
      { "label": "Applications", "text": "Forms of up to 25 questions, reviewed with Accept and Deny buttons that message the applicant." },
      { "label": "Custom commands", "text": "STScript, a Scratch-like language for your own commands, sandboxed so a script can't do more than its author." }
    ],
    "note": "Also: moderation with numbered cases, vouches, Twitch live alerts, partnerships, role menus, a starboard, and a web dashboard with Discord login. /docs lists every command straight from the bot, so the list never goes out of date. It reads DonutSMP data but can't run in-game commands; the server's data is read-only to every bot.",
    "link": { "label": "", "url": "" },
    "guide": { "label": "Read the tutorial (PDF)", "url": "/files/DonutDuck-Tutorial.pdf" },
    "source": "https://github.com/UniversalWebX/vortalsiterepo/tree/main/donutduck",
    "visual": "giveaway"
  },
  {
    "id": "windhawk",
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
