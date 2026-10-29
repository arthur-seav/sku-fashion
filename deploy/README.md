# Deploying SKU-Fashion to a VPS

A short-lived demo deployment. One Docker Compose project runs everything: Caddy for HTTPS, the Django app, PostgreSQL and an hourly scheduler. Tested on the build machine with the production image; the VPS steps are run one at a time.

```
Internet ──80/443──▶ caddy container ──▶ web container (gunicorn + Django) ──▶ db container (PostgreSQL 17)
                        │
                        └── /media/* served from ./media (read-only)
                     scheduler container: cancel_unpaid_orders every hour
```

| Piece | Where | Notes |
|---|---|---|
| `Dockerfile` | repo root | Python 3.14 slim, runs as uid 10001, static files collected at build time and served by WhiteNoise |
| `compose.yaml` | repo root | `db`, `web`, `scheduler`, `caddy`. Only Caddy publishes public ports; Docker's port rules bypass ufw, so nothing else may. `web` is also on `127.0.0.1:8034` for debugging from the server itself |
| `.env.production.example` | repo root | Copy to `.env` on the server. Secrets are generated on the server |
| `deploy/Caddyfile` | this folder | Site block for `{$SITE_DOMAIN}`, mounted into the `caddy` container |

`DJANGO_PRODUCTION=1` (set by `compose.yaml`) switches on HTTPS-only cookies, the HTTPS redirect, HSTS and hashed static files. Development is unaffected.

## Steps

Run as your own sudo-capable account on the VPS. Docker Engine with the compose plugin must be installed, and ports 80 and 443 must be free and allowed in ufw.

1. **Check the server** (read only): `free -h; df -h /; docker --version; docker compose version; sudo ss -tulpn; sudo ufw status verbose`.
2. **Get the code.** The repo is private, so create a read-only deploy key on the VPS (`ssh-keygen -t ed25519 -f ~/.ssh/sku-fashion-deploy -N ""`), add the public key to GitHub → repo → Settings → Deploy keys (no write access), then clone into `/srv/sku-fashion`.
3. **Configure.** `cp .env.production.example .env`, fill in the two secrets and `ACME_EMAIL`, `chmod 600 .env`. Create the upload folder for the container user: `mkdir -p media && sudo chown 10001:10001 media`.
4. **Check the configuration** (read only): `sudo docker compose config --quiet && echo OK`.
5. **Start.** `sudo docker compose up -d --build`, then `sudo docker compose exec web python manage.py seed_demo`. Watch `sudo docker compose logs -f caddy` until the certificate is issued.
6. **Verify** from another network: storefront, login, back-office, a receipt upload, product images.

## Day-to-day

```bash
cd /srv/sku-fashion
sudo docker compose ps                          # status
sudo docker compose logs -f web                 # requests, errors, and the e-mails (console backend)
git pull && sudo docker compose up -d --build   # deploy a new version of main
```

Reset the demo data:

```bash
sudo docker compose exec web python manage.py flush --no-input
sudo rm -rf media/products media/receipts
sudo docker compose exec web python manage.py seed_demo
```

## Known limits

- **Certificates.** sslip.io is not on the Public Suffix List, so every sslip.io site shares one Let's Encrypt weekly quota. With `ACME_EMAIL` set, Caddy falls back to ZeroSSL. If both fail, use a real domain.
- **Uploads are public.** Caddy serves `/media/` to anyone with the URL, payment receipts included. Testers must not upload real receipts.
- **E-mail** is only printed to `docker compose logs web`.

## Teardown

```bash
cd /srv/sku-fashion && sudo docker compose down -v --rmi local   # -v deletes the database and certificates
sudo rm -rf /srv/sku-fashion
```

Then delete the VPS deploy key in GitHub → Settings → Deploy keys, and close 80/443 in ufw if nothing else needs them.
