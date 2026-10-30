#!/bin/bash
# Crypto Intelligence — Let's Encrypt HTTPS setup (Phase 10, Stage A).
#
# Usage:
#   DOMAIN=example.com CERTBOT_EMAIL=you@example.com ./scripts/setup-https.sh
#   ./scripts/setup-https.sh renew        # renew + reload nginx
#
# Steps (first run):
#   1. Validate DOMAIN (must be real, never a placeholder).
#   2. Start Nginx with the HTTP config, which serves
#      /.well-known/acme-challenge/ from the certbot
#      webroot volume (DNS must already point the domain
#      at this VPS, and ports 80/443 must be open).
#   3. Obtain a certificate with certbot (webroot mode).
#   4. Switch Nginx to nginx/production.conf and verify
#      an HTTPS request succeeds.
#   5. ONLY THEN enable HSTS in production.conf and reload.
#
# Renewal (install as a cron job, see the deployment
# guide): run this script with `renew` twice a day; it
# renews certificates due for renewal and reloads Nginx.
# No secrets are printed by this script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: 'docker compose' is required." >&2
    exit 1
fi

if [ "${1:-}" = "renew" ]; then
    docker compose --profile certbot run --rm certbot renew --quiet
    docker compose exec nginx nginx -s reload
    echo "OK certificates renewed (if due) and nginx reloaded"
    exit 0
fi

DOMAIN="${DOMAIN:-}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "YOUR_DOMAIN" ] || [ "$DOMAIN" = "admin.example.com" ]; then
    echo "ERROR: set DOMAIN to the real domain (not a placeholder) before running this script." >&2
    exit 1
fi
if ! printf '%s' "$DOMAIN" | grep -Eq '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'; then
    echo "ERROR: DOMAIN does not look like a valid domain: $DOMAIN" >&2
    exit 1
fi

EMAIL_ARGS=(--register-unsafely-without-email)
if [ -n "$CERTBOT_EMAIL" ]; then
    EMAIL_ARGS=(--email "$CERTBOT_EMAIL")
fi

echo "Step 1: starting Nginx with the HTTP config for the ACME challenge"
docker compose up -d nginx

echo "Step 2: obtaining a certificate for $DOMAIN"
docker compose --profile certbot run --rm certbot certonly \
    --webroot -w /var/www/certbot -d "$DOMAIN" \
    "${EMAIL_ARGS[@]}" --agree-tos --non-interactive

echo "Step 3: switching Nginx to the production (HTTPS) config"
# The template ships with YOUR_DOMAIN placeholders; on
# this deployment host only, replace them with the real
# domain (this mutates the server copy, not the repo
# template that is committed — re-cloning restores it).
sed -i "s/YOUR_DOMAIN/$DOMAIN/g" nginx/production.conf
NGINX_CONFIG_FILE=./nginx/production.conf docker compose up -d nginx
sleep 3

echo "Step 4: verifying HTTPS before enabling HSTS"
if ! curl -fsS --max-time 15 "https://$DOMAIN/" >/dev/null; then
    echo "ERROR: HTTPS check failed for https://$DOMAIN/ — HSTS NOT enabled." >&2
    echo "Check DNS (A record -> this VPS), firewall (443 open), and the certificate, then re-run this script." >&2
    exit 1
fi

echo "Step 5: HTTPS verified — enabling HSTS in nginx/production.conf"
sed -i 's|^[[:space:]]*# add_header Strict-Transport-Security|    add_header Strict-Transport-Security|' nginx/production.conf
NGINX_CONFIG_FILE=./nginx/production.conf docker compose up -d nginx
curl -fsS --max-time 15 -I "https://$DOMAIN/" | grep -i "strict-transport-security" \
    || echo "WARNING: HSTS header not observed in the HTTPS response; check nginx/production.conf"
echo "OK HTTPS is live for $DOMAIN with HSTS enabled"
echo "Renewal cron (install on the VPS, twice daily):"
echo "  0 3,15 * * * cd $ROOT && docker compose --profile certbot run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload"
