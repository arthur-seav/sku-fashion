# Deploying SKU-Fashion to a VPS

A short-lived demo deployment: Docker Compose runs the app and PostgreSQL, and Caddy on the host terminates HTTPS. Tested on the build machine with the production image; the VPS steps are run one at a time.

```
Internet ──443──▶ Caddy (host) ──▶ 127.0.0.1:8034 ──▶ web container (gunicorn + Django)
                    │                                        │
                    └── /media/* served from disk            └──▶ db container (PostgreSQL 17)
                                                             scheduler container: cancel_unpaid_orders hourly
```

| Piece | Where | Notes |
|---|---|---|
| `Dockerfile` | repo root | Python 3.14 slim, runs as uid 10001, static files collected at build time and served by WhiteNoise |
| `compose.yaml` | repo root | `db`, `web`, `scheduler`. The only published port is `127.0.0.1:8034`, because Docker's port rules bypass ufw |
| `.env.production.example` | repo root | Copy to `.env` on the server. Secrets are generated on the server |
| `deploy/Caddyfile` | this folder | Site block for `202-61-200-81.sslip.io` |

`DJANGO_PRODUCTION=1` (set by `compose.yaml`) switches on HTTPS-only cookies, the HTTPS redirect, HSTS and hashed static files. Development is unaffected.

## Steps

Run as your own sudo-capable account on the VPS.

1. **Check the server** (read only): `lsb_release -a; free -h; df -h /; docker --version; caddy version; sudo ss -tulpn; sudo ufw status verbose; apt-cache policy docker.io docker-compose-v2 caddy`.
2. **Install** Docker and Caddy: `sudo apt install docker.io docker-compose-v2 caddy`. Do not add your user to the `docker` group (it is root-equivalent); use `sudo docker`.
3. **Get the code.** The repo is private, so create a read-only deploy key on the VPS (`ssh-keygen -t ed25519 -f ~/.ssh/sku-fashion-deploy -N ""`), add the public key to GitHub → repo → Settings → Deploy keys (no write access), then clone into `/srv/sku-fashion`.
4. **Configure.** `cp .env.production.example .env`, fill in the two secrets, `chmod 600 .env`. Create the upload folder for the container user: `mkdir -p media && sudo chown 10001:10001 media`.
5. **Start.** `sudo docker compose up -d --build`, then `sudo docker compose exec web python manage.py seed_demo`.
6. **Expose.** Put `deploy/Caddyfile` at `/etc/caddy/Caddyfile` (set the email), `sudo systemctl reload caddy`, `sudo ufw allow 80/tcp && sudo ufw allow 443/tcp`. Watch `sudo journalctl -u caddy -f` until the certificate is issued.
7. **Verify** from another network: storefront, login, back-office, a receipt upload, product images.

## Day-to-day

```bash
cd /srv/sku-fashion
sudo docker compose ps                     # status
sudo docker compose logs -f web            # requests, errors, and the e-mails (console backend)
git pull && sudo docker compose up -d --build   # deploy a new version of main
```

Reset the demo data:

```bash
sudo docker compose exec web python manage.py flush --no-input
sudo rm -rf media/products media/receipts
sudo docker compose exec web python manage.py seed_demo
```

## Known limits

- **Certificates.** sslip.io is not on the Public Suffix List, so every sslip.io site shares one Let's Encrypt weekly quota. With an `email` in the Caddyfile, Caddy falls back to ZeroSSL. If both fail, use a real domain.
- **Uploads are public.** Caddy serves `/media/` to anyone with the URL, payment receipts included. Testers must not upload real receipts.
- **E-mail** is only printed to `docker compose logs web`.

## Teardown

```bash
cd /srv/sku-fashion && sudo docker compose down -v   # -v also deletes the database volume
sudo rm /etc/caddy/Caddyfile && sudo systemctl reload caddy   # or restore the previous Caddyfile
sudo ufw delete allow 80/tcp && sudo ufw delete allow 443/tcp
sudo rm -rf /srv/sku-fashion
```

Then delete the VPS deploy key in GitHub → Settings → Deploy keys.
