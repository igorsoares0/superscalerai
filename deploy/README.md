# Deploying

One box, two containers: uvicorn behind Caddy. Postgres is Neon and object
storage is R2, so nothing stateful lives here except Caddy's certificates.

The order below exists because `ENVIRONMENT=production` turns the config
checks on, and those checks are the fastest way to find everything you still
haven't set — the app prints every problem at once and refuses to start.

## Once, on a fresh server

1. `git clone` into `/opt/superscaler`.
2. `cp .env.example .env` and fill it in. Start with `ENVIRONMENT=production`
   and run `docker compose up app` — the boot error is your remaining
   checklist. Repeat until it starts.
   The parts nothing can check for you:
   - `DATABASE_URL` — the Neon **direct** connection string, not `-pooler`
     (Alembic needs the direct one).
   - `PADDLE_PRICE_BASIC` / `PADDLE_PRICE_PRO` — the live price ids. Nothing in
     the string distinguishes a live id from a sandbox one, which is why the
     check compares against the known sandbox pair.
   - `LEGAL_*` — the name, address, contact and governing law printed on
     /terms, /privacy and /refunds.
   - `SITE_DOMAIN` / `ACME_EMAIL` — read by compose, for Caddy.
3. Point the domain's A/AAAA records at the server before starting Caddy:
   Let's Encrypt validates over port 80, so a wrong DNS record is a failed
   certificate and a rate limit on retries.
4. Hetzner Cloud Firewall: 80 and 443 open to the world, 22 only from your IP.
5. `sudo cp deploy/superscaler.service /etc/systemd/system/` then
   `sudo systemctl enable --now superscaler`.
6. Register the Paddle webhook against `https://<domain>/billing/webhook/paddle`
   and put that notification setting's secret in `PADDLE_WEBHOOK_SECRET`.

## Deploying a change

`sudo systemctl restart superscaler` (rebuilds, recreates, migrates on boot).

In-flight jobs die with the old container. The next boot marks them failed and
refunds the credits automatically, but the user loses the result — deploy when
it's quiet until graceful drain exists (LAUNCH.md, block 3).

## Memory and CPU on a shared box

This box also runs the Next.js apps and the other Python projects, so the
compose file is sized as a guest, not an owner: `MAX_CONCURRENT_JOBS=1`,
`mem_limit: 3.5g`, `cpus: 2.0`.

The numbers come from measurement: the app idles at 100 MB, and a single job
peaks at ~3 GB for 60-90 seconds at `MAX_IMAGE_PX=3072`. The limit has to cover
concurrency × peak — change one, change the other.

Two things follow from sharing:

- **Give every other project on this box a `mem_limit` too.** Over its limit,
  only that container dies. Without limits the kernel picks the victim during
  an out-of-memory event, and it tends to pick the largest process, which may
  well be a bystander.
- **One reverse proxy for all of them.** Only one process can hold ports 80 and
  443. If something already serves them here, drop the `caddy` service from
  this compose file and move the site block from `Caddyfile` into the existing
  proxy's config — keeping the headers and the `X-Forwarded-For` override,
  which is what makes `TRUST_PROXY_HEADERS=true` safe.

Raising throughput later doesn't need a bigger box: the strip-wise rewrite of
the post-processor drops the peak to a few hundred MB, which is what buys back
`MAX_CONCURRENT_JOBS` (LAUNCH.md, block 4).

## After the first real checkout

The CSP in `Caddyfile` ships as `Content-Security-Policy-Report-Only`. Run the
sandbox checkout, watch the browser console for violations, fix the directives,
then rename the header to enforce it. Paddle and the Tailwind CDN are the two
things whose exact hosts the source doesn't tell you.
