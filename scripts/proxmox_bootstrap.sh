#!/bin/bash
# Idempotent host bootstrap for CT 100 (fantasy-edge). Run as root ON the
# container: `ssh root@10.51.24.34 "pct exec 100 -- bash -s" < scripts/proxmox_bootstrap.sh`.
#
# Every step here is written to be safe to re-run: `apt-get install` on an
# already-installed package is a no-op, `systemctl enable` on an already-
# enabled unit is a no-op, `mkdir -p` doesn't fail if the dir exists, and
# the nginx config / systemd unit / cron entry are all written idempotently
# (overwrite-with-same-content or check-before-append) rather than assuming
# a pristine host.
set -euo pipefail

REPO_DIR=/opt/fantasy-edge
DATA_DIR=/mnt/data/fantasy-edge
BACKUP_DIR=/opt/backups/fantasy-edge

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
else
  echo "already installed: $(docker --version)"
fi

echo "==> Node 22 (host-level; the dashboard itself builds inside Docker, but
     scripts/tooling on this box may want a matching runtime)"
if ! command -v node >/dev/null 2>&1 || [ "$(node --version | cut -d. -f1 | tr -d v)" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
else
  echo "already installed: $(node --version)"
fi

echo "==> nginx + apache2-utils (htpasswd)"
apt-get update -y
apt-get install -y nginx apache2-utils

# CONSTRAINT #18's lesson generalizes here: bind-mount dirs created by this
# script must be owned by the container's UID (1001), not root, or the
# fantasy user inside the containers gets a silent PermissionError the
# first time it writes.
echo "==> Data directories (chowned to container uid 1001, not left root-owned)"
mkdir -p "$DATA_DIR"/{postgres,redis,models,logs}
chown -R 1001:1001 "$DATA_DIR/models" "$DATA_DIR/logs"
mkdir -p "$BACKUP_DIR"

echo "==> nginx site config (CONSTRAINT #11: system nginx, not containerized)"
cat >/etc/nginx/sites-available/fantasy-edge <<'NGINX'
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

}
NGINX

ln -sf /etc/nginx/sites-available/fantasy-edge /etc/nginx/sites-enabled/fantasy-edge
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx

echo "==> systemd unit: compose up on boot"
cat >/etc/systemd/system/fantasy-edge.service <<UNIT
[Unit]
Description=Fantasy Edge Docker Compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable fantasy-edge.service

echo "==> Daily backup cron (7-day retention)"
cat >/usr/local/bin/fantasy-edge-backup.sh <<BACKUP
#!/bin/bash
set -euo pipefail
cd "$REPO_DIR"
mkdir -p "$BACKUP_DIR"
# -T is safe here: nothing is piped INTO this exec, so there's no stdin
# for it to consume out from under a later line in this script.
docker compose exec -T postgres pg_dump -U \${POSTGRES_USER:-fantasy} \${POSTGRES_DB:-fantasy_edge} \\
  | gzip > "$BACKUP_DIR/pg-\$(date +%F).sql.gz"
find "$BACKUP_DIR" -name 'pg-*.sql.gz' -mtime +7 -delete
BACKUP
chmod +x /usr/local/bin/fantasy-edge-backup.sh

CRON_LINE="0 5 * * * /usr/local/bin/fantasy-edge-backup.sh >> /var/log/fantasy-edge-backup.log 2>&1"
# `grep -v` on an empty/absent crontab exits 1 ("no lines selected"), and
# under `set -e -o pipefail` that aborts the WHOLE script right here on a
# fresh host with no existing crontab - silently, before the final
# "Bootstrap complete" message ever prints. The `|| true` is load-bearing:
# without it this line never actually installs the cron entry, and nothing
# after it in the script runs either. Found by re-running the script and
# noticing crontab -l came back empty and the final echo never printed.
( crontab -l 2>/dev/null | grep -vF "fantasy-edge-backup.sh" || true ; echo "$CRON_LINE" ) | crontab -

echo "==> Bootstrap complete"
echo "Next: cd $REPO_DIR && docker compose up -d"
