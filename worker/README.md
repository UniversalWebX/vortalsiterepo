# vortal.space Worker

`site/` is the website, served as static files. `site.js` here handles the rest:

| Path | What it does |
| --- | --- |
| `POST /api/contact` | The contact form at vortal.space/contact. Saves the message to the inbox. |
| `/api/admin/*` | The private inbox panel at **vortal.space/admin**. Needs your key. |
| `email()` | Mail that Cloudflare Email Routing sends to this Worker. |

Messages live in the free D1 database `vortal-inbox` (schema in `migrations/`).

## 1. Set your panel key (required for /admin)

From the repo folder:

```bash
npx wrangler secret put ADMIN_KEY
```

Type a long key you'll remember (or keep in a password manager). Open vortal.space/admin and enter it.
Ten wrong keys from the same network lock the panel for 15 minutes.

## 2. Contact form protection (built in)

- A hidden "website" field that only bots fill in: those messages are silently dropped.
- Forms sent within 2.5 seconds of opening the page are refused.
- Five messages per visitor per hour. Visitors are identified by a hash of their IP, never the IP.
- Messages from other websites (a different `Origin`) are refused.

## 3. Email (optional, free) — currently placeholders

Everything below is off until you fill in the blanks in `wrangler.jsonc` → `vars`.

1. **Enable Email Routing:** Cloudflare dashboard → vortal.space → **Email → Email Routing** → enable.
   Cloudflare adds the DNS records for you.
2. **Verify your address:** under **Destination addresses**, add your own email and click the link it sends.
3. **Route an address to this Worker:** under **Routing rules**, create `contact@vortal.space` →
   action **Send to a Worker** → `vortalsiterepo`.
4. **Fill in the placeholders** in `wrangler.jsonc`:
   - `FORWARD_TO`: your verified address. Mail to contact@vortal.space is saved to the inbox, forwarded
     here, and the sender gets an automatic "we got your message" reply (`AUTO_REPLY`).
   - `MAIL_FROM` + `NOTIFY_TO`, and uncomment `send_email` with the same `NOTIFY_TO` address, to get an
     email copy of every contact-form message.
5. Deploy: `npx wrangler deploy`. The panel's **Email setup** view shows what's switched on.

Auto-replies are skipped for mailing lists, bounces and no-reply senders, so two robots can't reply
to each other forever. Cloudflare only lets the Worker reply once per email, to the sender, from the
address it was sent to.
