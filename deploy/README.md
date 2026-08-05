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

## Memory

`mem_limit: 6g` in the compose file is sized for `MAX_CONCURRENT_JOBS=2` at the
measured worst case of ~3 GB peak for a single job at `MAX_IMAGE_PX=3072`. The
limit has to cover concurrency × peak, not one job: under it the kernel kills
uvicorn — every request dies, not just the greedy job. Change one, change the
other. Halving the peak is a known, unstarted piece of work (LAUNCH.md block 4).

## After the first real checkout

The CSP in `Caddyfile` ships as `Content-Security-Policy-Report-Only`. Run the
sandbox checkout, watch the browser console for violations, fix the directives,
then rename the header to enforce it. Paddle and the Tailwind CDN are the two
things whose exact hosts the source doesn't tell you.
