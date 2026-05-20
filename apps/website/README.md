# Agora Landing Site

Single-file static HTML for **agoraproto.org**. Tells visitors what
Agora is, shows the on-chain receipts, links them at the SDK / API /
GitHub. Designed for crypto-curious dev audiences first, polished
enough that an investor / journalist landing on it from a tweet also
gets the picture in 30 seconds.

## What's in here

```
apps/website/
├── index.html        # entire site: HTML + inline CSS + inline SVG + tiny JS
└── README.md         # this file
```

No build step. No npm dependencies. No JavaScript framework. One file,
opens in any browser, deploys behind any static server. SVG
illustrations are inline (no external assets to break), CSS is inline
(no FOUC on first load), code-block syntax highlighting is hand-marked
in HTML (no Prism / highlight.js dependency).

If you change content, just edit `index.html`. There is no `npm run
build`.

## Deploying to agoraproto.org

The existing production server (`agora-1` on Hetzner Cloud) already
runs Caddy as a reverse proxy in front of the FastAPI backend and the
Next.js dashboard. We're going to:

1. Move the **dashboard** from `agoraproto.org` to `dashboard.agoraproto.org`.
2. Put the **new landing site** at `agoraproto.org` (the bare apex).

### Step 1 — DNS

Add an A record (or CNAME) for `dashboard.agoraproto.org` pointing at
the same Hetzner Cloud IP as the apex. Once it's resolving, Caddy can
issue an SSL cert for it automatically.

### Step 2 — Place the static file on the server

```bash
ssh root@188.245.39.250
mkdir -p /var/www/agoraproto.org
# pull the file from the repo
cp /opt/agora/apps/website/index.html /var/www/agoraproto.org/index.html
chown -R www-data:www-data /var/www/agoraproto.org
```

(Or symlink it so future `git pull` updates the live site:
`ln -sf /opt/agora/apps/website/index.html /var/www/agoraproto.org/index.html`.
Pick whichever you prefer — symlink keeps the deploy step to one git
pull, but means a broken commit goes live instantly.)

### Step 3 — Caddyfile

Add two blocks in `/etc/caddy/Caddyfile` (replace the existing
agoraproto.org block):

```caddy
# Marketing / landing — static HTML
agoraproto.org, www.agoraproto.org {
    root * /var/www/agoraproto.org
    file_server
    encode gzip zstd
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer-when-downgrade"
    }
}

# Dashboard (the existing Next.js app) moves to its own subdomain
dashboard.agoraproto.org {
    reverse_proxy 127.0.0.1:3000   # adjust if the dashboard listens elsewhere
    encode gzip zstd
}
```

`api.agoraproto.org` keeps its existing block — nothing changes for the
FastAPI service.

### Step 4 — Reload Caddy

```bash
caddy fmt --overwrite /etc/caddy/Caddyfile     # optional, prettifies
caddy validate --config /etc/caddy/Caddyfile   # MUST pass before reload
systemctl reload caddy
```

Caddy will issue a fresh Let's Encrypt cert for `dashboard.agoraproto.org`
on first request. No restart needed.

### Step 5 — Sanity check

```bash
curl -sI https://agoraproto.org | head -3
# HTTP/2 200
# server: Caddy
# content-type: text/html; charset=utf-8

curl -sI https://dashboard.agoraproto.org | head -3
# HTTP/2 200  (or 302 to a Next.js entry path)

curl -sI https://api.agoraproto.org/healthz | head -3
# HTTP/2 200 — should still work unchanged
```

## Updating the site

```bash
# on your dev machine:
# edit apps/website/index.html
git commit -am "site: copy tweak"
git push

# on the server:
cd /opt/agora && git pull
# if you used the symlink approach: nothing else to do.
# if you copied the file: copy it again.
cp apps/website/index.html /var/www/agoraproto.org/index.html
```

No cache busting needed — the HTML has no fingerprinted assets, and
Caddy doesn't add aggressive cache headers by default. If you ever
want CDN-side caching, add a `Cache-Control` header in the Caddy
block.

## Local preview

```bash
cd apps/website
python3 -m http.server 8000
# then: open http://localhost:8000
```

Or just double-click `index.html` — it works as a file:// URL too,
because there are no fetch() calls or external assets.

## What goes here vs. /docs

The landing is the **30-second pitch**. The repo's `docs/` directory
(`x402.md`, all ADRs, milestone logs) is the **long form**. The site
links to those for anyone who wants depth.

If something changes that the landing should reflect (a new
milestone, a mainnet deploy, an audit completion), edit `index.html`
directly. There is no CMS. There is no auto-pull-from-DB. The site
is intentionally a static artifact you commit, so what's live is
exactly what's in git.
