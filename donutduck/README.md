# 🍩🦆 DonutDuck

A multi-purpose Discord bot for DonutSMP. Data comes from
[donutstats.org](https://donutstats.org) — no API key needed.

## Commands

| Command | What it does |
| --- | --- |
| `/stats <player>` | Balance, shards, K/D, playtime, blocks, shop/sell, vouches |
| `/skin <player>` | Renders the player's skin |
| `/ah [item]` | Items on the auction house with prices and sellers |
| `/price <item>` | Cheapest price, listing count, sellers |
| `/leaderboard <board>` | Any of the 10 leaderboards, paginated |
| `/rank <player> <board>` | Finds a player's position on a leaderboard |
| `/economy [pages]` | Sums the money leaderboard |
| `/status` | Server player count, version, MOTD |
| `/ping` | Bot and API latency |
| `/help` | Command list |

### Stat tracking

| Command | What it does |
| --- | --- |
| `/track <stat> <player> [channel]` | Reports that stat's change every 12 hours |
| `/untrack <stat> <player>` | Stops a tracker |
| `/trackers` | Lists this server's trackers and when each next fires |
| `/history <stat> <player>` | Recorded snapshots, with per-day rate |

A background loop wakes every 30 minutes and processes any tracker whose last
run was over 12 hours ago. That's deliberate: a restart doesn't reset
anyone's schedule, and a tracker started at 3pm reports at 3am rather than
whenever the bot last booted. Adding a tracker takes a baseline reading
immediately, so the first report has something to compare against. Multiple
stats on the same player share a single API call per cycle. Snapshots older
than 90 days are pruned automatically. Limit is 25 trackers per server.

### In-game command mirrors

`/bal` `/shards` `/kills` `/deaths` `/playtime` `/mobskilled` `/blocksbroken`
`/blocksplaced` `/baltop` — each mirrors the in-game command of
the same name and takes a player argument.

`/donut <command>` looks up any DonutSMP command and says what it does and
whether DonutDuck can run it.

**Important:** the DonutSMP API is read-only — there is no endpoint that
executes a command on the server. Commands that change game state (`/pay`,
`/sethome`, `/tpa`, `/sell`, `/shop`) can't be run from Discord by this or any
other bot. Those are documented in `/donut` rather than mirrored. To add a new
mirror for an informational command, append to `QUICK_STATS` in
`cogs/commands.py`; the slash command is generated from it.

### Giveaways

| Command | What it does |
| --- | --- |
| `/giveaway start <prize> <duration> [winners] [role] [channel] [mode] [claim_hours]` | Starts one |
| `/giveaway end <id>` | Ends early and draws winners |
| `/giveaway reroll <id> [count]` | Redraws, never repeating a previous winner |
| `/giveaway list` | Running giveaways with live entry counts |
| `/giveaway getdata` | Tabbed browser: overview, running, ended, winners, unclaimed |
| `/giveaway edit <id>` | Change prize, winners, description, or extend the time |
| `/giveaway cancel <id>` | End it with no winners |
| `/giveaway claimtime <id> <hours>` | Change the claim window on a live giveaway |
| `/giveaway claimdefault <hours>` | This server's default claim window |
| `/giveaway entries <id>` | Entry count for one giveaway |

Durations are written like `30m`, `2h`, `3d`, `1d12h`, `1w`. Entries are stored
in the database rather than as reactions, so counts survive restarts and can't
be inflated by removing and re-adding a reaction. The entry button toggles —
pressing it again leaves. A loop checks every 30 seconds for giveaways that
have run out, and each active giveaway's button is re-registered on startup so
old messages keep working after a redeploy.

**Entry counts are debounced.** The live entry number on a giveaway message
updates at most once every 5 seconds via a background loop, using a partial
message so no fetch is needed.

This fixed a real bug where giveaways stopped working past roughly 40 entries.
Every button press used to do a fetch *and* an edit — two API calls against a
limit of about five edits per five seconds per message. A burst of entries
queued up behind the rate limiter, and because each press awaited that edit,
interactions began missing Discord's 3-second acknowledgement window and
failed. Entries were always being saved correctly; it was the UI update that
jammed. 100 entries now cost 1 API call instead of 200.

**Restarts are safe.** End times live in the database, not in memory, so a
giveaway counting down survives the bot going away. If the bot is offline at
the moment a giveaway should end, it ends on the next poll after it comes back
— late rather than lost. Entry buttons and unclaimed Claim buttons are both
re-registered at startup.

**Claiming asks for an IGN.** Pressing Claim opens a modal for the winner's
Minecraft name before the ticket exists, so staff aren't chasing it afterwards.
The claim channel is named `claim-0007-winner` and its topic reads
`Hosted by X · won Y · winner Z`, so tickets are identifiable from the sidebar.

**Vouching happens at close, not open.** The Vouch button now appears when a
giveaway ticket is closed — by then the trade has actually happened — and
those tickets get 60 seconds before deletion instead of 10 so there's time to
press it.

**Winners must press Claim.** Ending a giveaway posts a Claim button that only
winners can use; pressing it opens the ticket. Previously tickets opened
automatically, which left empty channels behind for winners who never came
back — and for the game modes below, the claim press is also where the choice
happens. `claim_hours` (default 24, `0` = unlimited) closes the window on
prizes nobody collects; expiry is announced so the host can `/giveaway reroll`.

**Entry rules.** `min_account_days` rejects accounts newer than N days — checked
at *entry*, so someone finds out immediately rather than believing they were in
the running. `bonus_role` plus `bonus_entries` gives a role extra tickets in the
draw (verified: a role worth 5× won ~60% of draws against a theoretical 62.5%).
One prize per person regardless of weighting.

**Claim windows** are customisable three ways: per giveaway at start, changed
later on a live giveaway with `/giveaway claimtime`, or as a server default
with `/giveaway claimdefault`. `0` means unlimited.

**Modes.** `/giveaway start mode:` offers:

- **Split or Steal** — requires exactly 2 winners (the command refuses
  otherwise). Each winner privately picks split or steal, hidden until both
  have chosen. Both split → they share it. One steals → that player takes it
  all. Both steal → nobody gets anything. A winner who never chooses counts as
  having split, since defaulting to steal would reward not participating.
- **Double or Keep** — the winner either keeps the prize (which opens their
  claim ticket) or doubles it, which **launches a brand-new giveaway worth
  twice as much** that they have to win again like everyone else.

  Doubling needs a number, and a prize is free text. Set `value:5000000` when
  starting, or name the prize something like `$5m` and it's parsed from that.
  With no value, the double button simply isn't shown rather than guessing.
  `/giveawaycap` and a 5-double ceiling stop it compounding out of control —
  five rounds turns $1M into $32M.

Choices are stored the first time and can't be changed by pressing again, and
resolution is written to the database, so a restart mid-game doesn't lose
anyone's decision. The outcome rules live in `games.py` as plain functions
with no Discord objects, so they're directly testable.

Winners are drawn only from entrants who are **still in the server** and still
hold the required role, so someone who left can't win. Eligibility is checked
with a REST fetch rather than the member cache, because the cache is empty
unless the privileged Members intent is enabled — reading it directly makes
every entrant look like they left. The pool is shuffled and resolved lazily,
so 500 entrants and 3 winners costs a handful of fetches rather than 500. When a giveaway ends,
each winner automatically gets a private claim ticket.

### Staff roles — set this up first

| Command | What it does |
| --- | --- |
| `/staffroles add <role>` | Marks a role as staff |
| `/staffroles remove` · `list` | Manage the list |
| `/ticketsync` | Adds staff roles to tickets that already exist |

**This is the switch that makes staff able to do things.** One list now drives
ticket visibility, giveaway access, activity checks and strikes. Previously
"staff" meant three different things depending on the command — tickets
checked the per-type role, giveaways required Manage Server — which is why
staff couldn't see most tickets or run giveaways.

New tickets add every staff role automatically. Channels created *before* you
added a role won't have it, so run `/ticketsync` once after setting the roles.

### Activity checks and strikes

| Command | What it does |
| --- | --- |
| `/activitycheck [hours] [channel] [strike]` | Pings staff to confirm they're active |
| `/strikes [member]` · `/strikelist` | View strikes |
| `/strike <member> <reason>` · `/strikeclear` | Give or clear strikes manually |
| `/strikelimit <n>` | Strikes before someone is flagged |

Every staff role is pinged and each member presses one button. When the
deadline passes, anyone who didn't respond gets a strike automatically and the
result is posted with who missed it and their new totals. Pass `strike:False`
for a check that doesn't punish. The strike-on-miss setting is stored on the
check, so a restart mid-check doesn't change the outcome.

### Legit votes

| Command | What it does |
| --- | --- |
| `/legit [member] [prize] [giveaway_id]` | Posts a legit check to the voting channel |
| `/legitresults <id>` | Tally for a vote |
| `/legitchannel <channel>` | Where votes are posted |

Legit / Not legit buttons with the count recorded in the database rather than
counted by hand off reactions. One vote per person, changeable. Passing
`giveaway_id` fills in the host and prize automatically.

### Minigames

`/guessnumber [low] [high]` — hints are posted publicly so the whole channel
narrows it down together. `/higherlower` — streak-based card game; a tie counts
as a win, since losing a long streak to a repeated card is just annoying.

### Vouches

| Command | What it does |
| --- | --- |
| `/vouch <user> [message]` | Vouch for someone |
| `/vouches [user]` | Someone's vouch count and recent vouches |
| `/vouchtop` | Most vouched members |
| `/vouchchannel <channel>` | Where vouches post *(Manage Server)* |
| `/vouchdelete <id>` | Remove a vouch record *(Manage Messages)* |

Giveaway claim tickets get a **Vouch** button. Pressing it shows a real
Discord user picker, then a message box, then posts:

```
@voucher: vouch @target their message
```

The picker is deliberate — a typed username can't be resolved reliably
(duplicate display names, nicknames, typos) and a vouch aimed at the wrong
person is worse than none. Discord modals only take text inputs, so it's a
select first, then the modal.

Posts default to channel `1519688084973686814` and use `/vouchchannel` when
set, falling back to the default if that channel is deleted. Mentions render
but don't ping, since a busy vouch channel would otherwise notify two people
per entry. Self-vouching, vouching bots, and repeat vouches for the same
person within 24 hours are all rejected. Every vouch is stored, which is what
makes `/vouches` and `/vouchtop` work.

### Tickets

| Command | What it does |
| --- | --- |
| `/ticketsetup <category> <log_channel> [max_open]` | Configures tickets, seeds default types |
| `/ticketpanel post [panel] [channel]` | Posts a panel |
| `/ticketpanel create <key> <title> [types]` | Saves a new panel |
| `/ticketpanel edit` · `refresh` · `delete` · `list` | Manages panels |
| `/tickettype add` | Adds a type (key, label, emoji, staff role, questions) |
| `/tickettype remove` · `toggle` · `role` · `questions` · `list` | Manages types |
| `/tickettype message` · `pings` · `preview` · `resetmessage` | Customises the opening message |
| `/close [reason]` | Closes the ticket, with transcript |
| `/ticketrename <name> [ticket]` | Renames a ticket from anywhere |
| `/ticketadd` · `/ticketremove` | Adds or removes someone from a ticket |
| `/tickets` | Staff view of all open tickets |
| `/ticketindex [show] [type]` | Every ticket with its reason |

Four types are seeded on first setup:

| Key | Label | Notes |
| --- | --- | --- |
| `staff` | Staff Application | 5 application questions |
| `pm` | Partner Manager Application | 5 application questions |
| `support` | Support | 2 questions |
| `giveaway-claim` | Giveaway Claim | Hidden from the panel; opened automatically for winners |

Panels are dropdowns, and a server can have **as many as it likes**. Each
panel gets its own numeric **ID**, its own dropdown, and its own title,
description, placeholder and subset of ticket types — a support desk in one channel, staff applications in another,
a catch-all somewhere else.

```
/ticketpanel create key:support   title:"Need help?"        types:support
/ticketpanel create key:apps      title:"Join the team"     types:staff,pm
/ticketpanel post   panel:apps    channel:#applications
```

`/ticketpanel list` shows every panel with its ID:

```
#1 · Need help?      (support)   #support        · support
#2 · Join the team   (apps)      #applications   · staff, pm
#3 · Store support   (store)     not posted yet  · support
```

Any `/ticketpanel` command takes either the ID or the name, so
`/ticketpanel edit panel:2` and `/ticketpanel edit panel:apps` are the same
thing. Autocomplete lists panels as `#2 · Join the team (apps)` and submits
the ID, so picking from the list is never ambiguous. IDs are stable — deleting
panel #3 doesn't renumber the others.

Each panel's dropdown has its own custom_id (`dd:ticket:select:apps`), which
is what keeps them independent: two panels offering different types don't
interfere, and one persistent view is registered per posted panel at startup.

`/ticketpanel post` with no panel gives the default one containing every
visible type. Type keys are validated when a panel is saved, so a typo is
caught immediately rather than producing an empty dropdown. `/ticketpanel
edit` changes a panel and redraws the posted message **in place**, keeping its
position in the channel; `types:all` resets it to every visible type.
`/ticketpanel refresh` redraws panels after you add or disable a ticket type
(Discord stores dropdown options on the message itself, so an existing panel
won't pick up new types until it's redrawn). `/ticketpanel delete` removes a
panel, optionally deleting the posted message too.

Each panel's select carries its key in the custom_id, and one persistent view
is registered per posted panel at startup — without that, custom panels would
stop responding after a restart while the default one kept working.

Inside a ticket, a "More actions" dropdown offers transcript, re-post index,
and priority flagging.

**Adding more types needs no code** — `/tickettype add` writes a row, and the
panel rebuilds its options from the database on every interaction, so a new
type is live immediately. Questions are passed pipe-separated
(`"Your IGN?|Why you?"`) and become a modal shown before the channel opens;
Discord caps modals at 5 inputs, which the command enforces.

**The opening message is customisable per type.** `/tickettype message` sets
the title, body, colour, image and footer; `/tickettype pings` controls whether
the opener and staff role get pinged and whether form answers are shown; and
`/tickettype preview` renders it without opening a ticket. `/tickettype
resetmessage` restores the default.

Placeholders: `{user}` mention · `{name}` display name · `{tag}` full tag ·
`{ticket}` number · `{type}` type label · `{reason}` derived reason ·
`{server}` server name · `{staff}` staff role mention. Type `\n` for a line
break — slash commands can't contain real newlines. Types you never customise
render exactly as before, and a customised `giveaway-claim` type is used for
prize claims too.

**Every ticket carries a reason**, shown in three places: a pinned index
message at the top of the channel, an index block at the head of the
transcript file, and `/ticketindex` for a staff overview of all tickets and
their reasons at once. The reason is derived from the answer to whichever
question actually asks *why* — matching on "why", "reason", "need help",
"issue" and similar — because on an application form the first question is
usually age or timezone, which makes a useless index entry. Giveaway claims
use the prize name. If nothing matches, the type's description is used, so the
index is never blank.

Transcripts open with that index (ticket number, type, reason, opener,
claimer, closer, close reason, timestamps), then the submitted answers, then
the conversation, and end with a per-participant message count.

Built-in types can be disabled but not deleted, so a server can't accidentally
remove the giveaway-claim plumbing. Each type can have its own staff role and
category, falling back to the server defaults. Closing a ticket posts a
transcript to the log channel and DMs a copy to the opener, then deletes the
channel after 10 seconds. Panels and in-ticket buttons are persistent views
with fixed custom_ids, so they survive restarts.

### Twitch live notifications

| Command | What it does |
| --- | --- |
| `/twitch add <streamer> <channel> [role] [message]` | Announce when they go live |
| `/twitch remove` · `/twitch list` · `/twitch test` | Manage and preview |

Needs free credentials from https://dev.twitch.tv/console/apps in
`TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`. Without them the cog still
loads and `/twitch` explains the setup instead of failing obscurely.

Auth uses the client-credentials flow, so nobody logs in with Twitch. One poll
every 2 minutes covers every streamer in every server, because Helix accepts
100 logins per request. Announcements are keyed on the **stream id**, not a
live flag, so a mid-stream disconnect and reconnect doesn't fire a second
ping — only a genuinely new broadcast does. Usernames are validated against
Twitch when added, so a typo fails immediately rather than silently never
firing. Custom messages support `{mention}`, `{name}`, `{title}`, `{game}`
and `{url}`.

### Applications

| Command | What it does |
| --- | --- |
| `/apply <form>` | Fill in an application |
| `/application setup <review_channel> [role]` | Creates the staff form with 8 default questions |
| `/application create` | Another form (Partner Manager, media, etc.) |
| `/application questions` · `toggle` · `delete` · `list` | Manage forms |
| `/applications` | Pending queue |

**Forms can have up to 25 questions.** Discord modals only allow 5 inputs, so
longer forms are split into pages of 5: submitting a page saves the answers
and shows a Continue button that opens the next modal. A modal can't open
another modal directly, but a button can — that bridge is what makes long
applications possible. Partial answers live in memory for 30 minutes and are
then dropped.

Submissions post to a review channel with Accept/Deny buttons, restricted to
Manage Server. Accepting can auto-assign a role; both outcomes DM the
applicant, and denials can carry a reason. The decision is written back onto
the review post so there's a record in context. Buttons carry the application
id in their custom_id, so they keep working after a restart. Guards included:
one pending application per person per form, a configurable reapply cooldown
after a denial (14 days default), and an atomic decision so two staff clicking
at once can't both resolve the same application.

**Overlap with tickets:** the ticket system also has staff-application types.
Tickets open a private channel for a conversation; this is a structured form
with a decision attached. Most servers want one or the other — run
`/tickettype toggle staff false` if you prefer this.

### Server features

| Command | What it does |
| --- | --- |
| `/welcome set` · `goodbye` · `autorole` · `off` | Greetings and a role for every joiner |
| `/rolemenu <key> <roles>` | Self-assign roles from a **dropdown** |
| `/rolemenudelete` | Remove a role menu |
| `/starboard [channel] [stars] [emoji]` | Repost popular messages |

Welcome and goodbye text supports `{user}`, `{name}`, `{tag}`, `{server}`,
`{count}` and `{id}`.

Role menus are a dropdown rather than literal reactions: no Manage Messages
needed to tidy stray reactions, no emoji collisions, a description per option,
and an optional cap on how many roles someone may hold. Deselecting removes
the role, and only roles the menu manages are ever touched. Menus are
persistent views, so they survive restarts. If a role sits above the bot's own
role the command refuses up front rather than failing later.

The starboard edits its existing post as the count changes and deletes it if
the message drops back below the threshold.

### Utilities

`/poll` uses **Discord's native poll object**, so Discord tallies the votes and
nobody can skew them by piling on reactions. `/remind` and `/reminders` are
checked every 30 seconds and stored in the database, so they survive restarts.
`/embed` posts a themed embed as the bot, and `/serverinfo` and `/userinfo`
give quick info — `/serverinfo` also shows DonutDuck's own counts for the
server.

### Dashboard

A web dashboard runs alongside the bot when configured.

```
DISCORD_CLIENT_ID=      # OAuth2 tab of the same Discord application
DISCORD_CLIENT_SECRET=
DASHBOARD_BASE_URL=     # e.g. https://yourname.mooo.com
DASHBOARD_PORT=8080
DASHBOARD_SECRET=       # python -c "import secrets;print(secrets.token_hex(32))"
```

Add `DASHBOARD_BASE_URL` + `/callback` as an OAuth2 redirect URI in the
Discord developer portal, or login will fail.

Login is Discord OAuth2 — not a shared password — because the dashboard shows
ticket reasons and application data, so it has to know *who* someone is. You
only see a server if you hold **Manage Server** there and the bot is in it, and
those permissions are read from Discord's own API rather than trusted from the
browser. Sessions are HMAC-signed cookies; tampering, forging or expiry all
invalidate them, and all user-supplied text is HTML-escaped. `/health` returns
JSON for uptime monitoring.

It's deliberately **read-mostly**: it shows tickets, applications, giveaways,
streams and counts, but actions stay in Discord where they're attributable.

### FreeDNS

FreeDNS gives you a **hostname, not hosting** — you still run the bot
somewhere. What it solves is a changing IP. Grab the "Direct URL" for your
subdomain from https://freedns.afraid.org/dynamic/ and set:

```
FREEDNS_UPDATE_URL=https://sync.afraid.org/u/YOURTOKEN/
```

The bot then refreshes the record every 10 minutes, skipping the call when the
IP hasn't changed. That URL is a credential — keep it out of any repo.

You still need to make the port reachable: forward `DASHBOARD_PORT` on your
router if self-hosting, and put a reverse proxy (Caddy or nginx) in front for
HTTPS. Set `DASHBOARD_BASE_URL` to the `https://` address once you do — the
session cookie only gets the `Secure` flag when it starts with `https`.

### Per-server appearance

| Command | What it does |
| --- | --- |
| `/serverprofile avatar` | Sets the bot's avatar **in this server only** |
| `/serverprofile nickname` | Sets its nickname here |
| `/serverprofile view` | Shows the current settings |
| `/serverprofile reset` | Back to the global default |

This uses `PATCH /guilds/{id}/members/@me`, which sets a guild-specific avatar
for the bot's own member — deliberately *not* `ClientUser.edit(avatar=...)`,
which is global and would change the bot's face in every server at once.

Takes an upload or a direct URL; accepts PNG, JPEG, GIF and WebP up to 8 MB.
Image types are sniffed from magic bytes rather than with `imghdr`, which was
removed in Python 3.13. discord.py 2.7 added `avatar` to `Member.edit`; on
older versions the cog calls the REST endpoint directly, so it works on 2.4+.

Discord rate limits avatar changes hard, so the command is capped at 2 per
hour per server and a 429 is reported in plain language rather than as an
error. Manage Server is required, and nickname changes also need the bot to
have **Change Nickname**.

### Private commands (one server only)

Locked to guild `1504931329156976721`:

| Command | What it does |
| --- | --- |
| `/player1bal` | Balance of `PlayerOne` |
| `/player2bal` | Balance of `PlayerTwo` |
| `/player3bal` | Balance of `PlayerThree` |
| `/balhis [player] [days]` | Balance history as a trading-style chart |

These are registered with `@app_commands.guilds(...)`, so Discord only ever
exposes them inside that one server — they aren't hidden globals, and no other
server can invoke them even knowing the names. Change `PRIVATE_GUILD_ID` in
`cogs/private.py` to move them, or edit `TRACKED` to change the three players.

A background poller samples all three balances every 3 hours into the same
`snapshots` table `/track` uses, and every manual `/player1bal`-style check adds
a point too. `/balhis` needs at least two points, so a fresh install shows a
"still collecting data" notice for the first few hours rather than an empty
chart. `/balhis` defaults to all three overlaid; pass a player to isolate one,
and `days` (1–90) to change the window.

### Partners

| Command | What it does |
| --- | --- |
| `/partner setup <channel> <invite> <description>` | Enables partnering and sets your listing |
| `/partner toggle <enabled>` | Turns partnering on or off |
| `/partner config` | Shows current settings |
| `/partner browse` | Servers open to partnering |
| `/partner request <server>` | Sends a request (autocompletes server names) |
| `/partner list` | Active and pending partnerships |
| `/partner remove <server_id>` | Ends a partnership |

Partnering is **off by default** and every command except `browse` and `list`
requires Manage Server. A partnership only forms when both sides accept, and
adverts are only ever posted into the channel each server nominated for
itself — so the bot can't be used to blast promos into servers that didn't opt
in. Requests arrive as an embed with Accept/Decline buttons that only the
target server's staff can press. Leaving a server disables its partnering
automatically.

## STScript — custom commands

| Command | What it does |
| --- | --- |
| `/st <id or name> [args]` | Run a script |
| `/stscript create <name>` | Write one (opens a code editor) |
| `/stscript edit` · `show` · `list` · `delete` · `settings` | Manage scripts |
| `/stscript test <code>` | Run without saving |
| `/stscript help` | The language reference |

A Scratch-like language for custom bot commands:

```
say Hello {user.name}!
set coins to 100
add 50 to coins
random roll from 1 to 6
if {roll} >= 4
  say You rolled {roll} and have {coins} coins — lucky!
else
  say You rolled {roll}. Unlucky.
end
repeat 3
  say Reminder {loop}
end
```

Statements: `say` `reply` `dm` `embed` `set` `add` `random` `repeat` `while`
`if`/`else` `wait` `role add|remove` `stop`. Built-in variables: `{user}`
`{user.name}` `{user.id}` `{server}` `{channel}` `{args}` `{arg1}…`, plus
`{loop}` inside a repeat.

### How it's kept safe

Scripts are user-written code running inside the bot, so the interpreter is
built to make that boring:

- **No `eval`, `exec`, `import` or attribute access anywhere.** Source is
  parsed into a fixed set of node types and walked by an interpreter that only
  knows those types — there's no route from script text to Python. Arithmetic
  uses a hand-rolled shunting-yard rather than `eval`. Statement dispatch is an
  explicit table, not `getattr`. Text like `__import__('os')` is stored as an
  inert string; verified with a canary file that never appears.
- **Everything is bounded:** 300 lines, 2000 statements, 500 loop iterations,
  5 levels of nesting, 15 messages, 5 seconds runtime, 10 seconds of `wait`,
  1500-character strings. Infinite loops and repeat-100000 both fail cleanly.
- **The interpreter performs no side effects.** It returns requested actions;
  the cog decides what's allowed. `role add` only works if the script's *author*
  has Manage Roles and the role sits below the bot, so scripts can't escalate.
  Scripts never ping `@everyone` or roles.
- Only staff can create or edit scripts; one run per person at a time.

Parse errors are reported with a line number when the script is saved, not
when someone runs it.

## Documentation

`/docs` lists every command with its usage and description, in a dropdown of
sections. The listing is generated by walking the live command tree, so it
can't drift out of date the way a hand-written list would — only the section
blurbs and setup steps are written by hand. `/docs section:Tickets` jumps
straight to one. `/help` remains the short version.

## Setup

1. **No API key needed.** Data comes from donutstats.org by scraping.
2. **Create a Discord bot** at https://discord.com/developers/applications →
   New Application → Bot → Reset Token. Under *Installation*, add the
   `applications.commands` and `bot` scopes, then use the generated URL to
   invite it. No privileged intents are needed.
3. **Configure and run:**

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your tokens
python -m donutduck.bot
```

Set `GUILD_ID` in `.env` while developing — slash commands appear in that
server instantly instead of taking up to an hour to propagate globally.

## Project layout

```
donutduck/
  bot.py          entrypoint, cog loading, command sync, error handler
  scraper.py      donutstats.org scraper: fetching, caching, HTML parsing
  twitch.py       Twitch Helix client: app tokens, batched stream lookups
  web.py          dashboard: OAuth login, sessions, guild views
  ddns.py         FreeDNS dynamic DNS updater
  games.py        minigame outcome rules, prize-value parsing, doubling cap
  permissions.py  one definition of "staff", used everywhere
  stscript.py     the STScript language: parser and sandboxed interpreter
  theme.py        the blue / pink / yellow palette, in one place
  chart.py        matplotlib balance charts, rendered off the event loop
  db.py           SQLite: trackers, snapshots, guild config, partnerships
  stats.py        one registry defining every stat, its API aliases and format
  utils.py        money/number/playtime formatting, embed builders
  paginator.py    button paginator that fetches pages lazily
  cogs/
    player.py       /stats /lookup /skin
    auction.py      /ah /ahsales /price
    leaderboard.py  /leaderboard /rank
    tracking.py     /track /untrack /trackers /history + the 12h loop
    partner.py      /partner group
    commands.py     in-game command mirrors + /donut reference
    tickets.py      ticket types, panel, modals, transcripts
    giveaways.py    giveaway lifecycle + automatic claim tickets
    streams.py      Twitch live notifications
    applications.py paged application forms + review workflow
    server.py       welcome, autorole, role menus, starboard
    utility.py      polls, reminders, embeds, info
    staff.py        staff roles, activity checks, strikes, legit votes
    minigames.py    guess the number, higher or lower
    scripts.py      STScript authoring and execution
    docs.py         /docs, generated from the command tree
    profile.py      per-server avatar and nickname
    private.py      guild-locked balance commands + /balhis
    general.py      /help /ping /status /economy
```

State lives in `donutduck.db` (SQLite, created on first run — set `DB_PATH`
to move it). Back that file up and trackers and partnerships survive a
redeploy. Everything is awaited, so nothing blocks the gateway heartbeat.

## Theming

Everything colour-related lives in `theme.py` — blue `#3B82F6`, pink
`#FF4FA3`, yellow `#FFCE3B`. Embeds pick a stable colour per subject via
`base_embed(..., accent="somekey")`, so a given player or stat always looks
the same across commands rather than every message being flat blue. Charts
assign the three colours positionally so two lines can never collide.
Editing `theme.py` retints the entire bot, embeds and charts together.

### Adding a stat

`stats.py` is the single source of truth. Add one `Stat(...)` entry and it
appears in `/track`, `/untrack`, `/history`, and the leaderboard choices at
once, with the right formatter and the right sense of which direction is
"good" (deaths going up gets a ⚠️).

## Data source

All data is scraped from **donutstats.org**, an unofficial community stats
site. No API key is required.

### Why scraping, and why not a browser

The official DonutSMP API needs a key from `/api` in-game, which is gated
behind account linking and wasn't obtainable. donutstats.org publishes the
same figures publicly.

Every page used is server-rendered PHP at a plain URL, so a normal HTTP GET
returns finished HTML. No headless browser is involved — driving Chromium
would add hundreds of MB of memory and seconds of latency per lookup for
byte-identical data.

### How the parser is built to survive redesigns

Pages are parsed from their **rendered text** using label-then-value regexes
("Money" followed by its value) rather than CSS classes. Class names change
with every restyle; the visible label is the thing the site exists to show.
Missing fields return `None` instead of raising, so one renamed label degrades
a single embed field rather than breaking a command.

Requests are serialised with a 1-second minimum gap, sent with an identifying
User-Agent, and cached for 5 minutes. The site refreshes roughly every 30
minutes, so caching costs nothing in freshness and spares it traffic.

### What this costs

- **Precision.** The site displays rounded values (`105.76B`, `216.71K`), so
  figures are less exact than the API's integers. `/balhis` charts are coarser
  and small 12-hour changes can read as zero.
- **Staleness.** donutstats.org refreshes about every 30 minutes.
- **Fragility.** It's a hobby site; a redesign can break parsing. Everything
  that reads it lives in `scraper.py`, so fixes are one file.

### Commands that couldn't survive the switch

| Removed | Why |
| --- | --- |
| `/lookup`, `/findplayer` | The site publishes no online status or coordinates |
| `/ahsales` | No transaction-history page exists |

`/ah` and `/price` changed shape: the site aggregates the auction house **per
item** (cheapest price, listing and seller counts, seller names) rather than
per listing, so there are no individual listing prices and no median or
average across listings. `/stats` gained a vouches field, which the site does
publish, and `/status` now reads the site's own server-stats page for player
count, peak, total economy, version and MOTD.

## Adding a command

Drop a new cog in `donutduck/cogs/`, add it to `COGS` in `bot.py`. Every cog
gets `self.bot.api` for API access and can reuse `PageView` for pagination.
