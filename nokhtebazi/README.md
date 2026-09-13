# Nokhtebazi

Dots and Boxes for friends: *nokhte bazi* (نقطه بازی) is Persian for "the dots game". Take turns joining
two dots; draw the fourth side of a box to claim it and draw again. Most boxes wins.

Live at **https://nokhtebazi.vortal.space**. Part of [Vortal](https://vortal.space).

## Ways to play

- **Online.** Create a room and share the link or the five-letter code. Up to six players; anyone who
  arrives after the game starts watches. Everyone sees each other's cursors.
- **On one device.** Play the computer, or pass the device between two to four players. An unfinished
  game is saved in the browser and can be resumed.
- **Four boards:** Quick 5 × 5, Classic 8 × 8, Big 12 × 12, and the 25 × 25 Marathon.
- **English and Persian**, switchable any time; Persian switches the layout to right-to-left.

## How it's built

```
worker.js            Cloudflare Worker + the Room Durable Object (one per table)
wrangler.jsonc       Cloudflare config: static assets, Durable Object, custom domain
public/engine.js     the rules, as pure functions, run by both the browser and the server
public/app.js        the client: screens, WebSocket, canvas board, computer opponent
public/index.html
public/style.css
```

- **The server decides every move.** The client sends "draw this line"; the room checks it's your turn
  and the line is free, closes boxes, keeps the score and passes the turn, then sends everyone the new
  board. A modified client can't fake a turn or a score.
- **One file of rules.** `engine.js` is imported by the Worker and the page, so a move means the same thing
  everywhere, and the computer opponent plays by the same rules.
- **Rooms survive restarts.** Each room saves its state in its Durable Object and closes itself six hours
  after its last activity. Live connections are WebSockets using hibernation, so idle rooms cost nothing.
- **Turns keep moving.** If the player to move disconnects, the turn passes to someone who's still here.

## Run and deploy

From this folder:

```bash
npx wrangler dev      # local, at http://localhost:8787
npx wrangler deploy   # live at nokhtebazi.vortal.space
```

The first deploy creates the Worker, the Room Durable Object, and the `nokhtebazi.vortal.space` custom
domain with its DNS record and certificate. Everything fits the Workers free plan.

### API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/rooms` | open a room: `{ name, color, size }` → `{ code, seat, token }` |
| `POST` | `/api/rooms/:code/join` | take a seat, reclaim yours with `token`, or watch once a game has started |
| `GET` | `/api/rooms/:code/socket?token=` | WebSocket: the server sends `room` (whole state + your seat) and `cursor` |

Messages a player sends on the socket: `move {kind, i}`, `cursor {x, y}`, `size {size}`, `start`,
`lobby` (back to the room after a game), and `leave`.
