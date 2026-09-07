#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-django}"
APP_DIR="${APP_DIR:-/opt/django-crm}"
REPO_URL="${REPO_URL:-https://github.com/avdiunichev/django-crm.git}"
DOMAIN="${DOMAIN:-_}"

if [[ ! -f /etc/django-crm.env ]]; then
  echo "Missing /etc/django-crm.env. Copy env.example there and fill secrets first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source /etc/django-crm.env
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in /etc/django-crm.env}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  git \
  nginx \
  postgresql \
  postgresql-contrib \
  python3 \
  python3-pip \
  python3-venv

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$APP_USER"

sudo -u postgres psql -v postgres_password="$POSTGRES_PASSWORD" <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'django_crm') THEN
    CREATE ROLE django_crm LOGIN PASSWORD :'postgres_password';
  ELSE
    ALTER ROLE django_crm WITH PASSWORD :'postgres_password';
  END IF;
END
$$;
SELECT 'CREATE DATABASE django_crm OWNER django_crm'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'django_crm')\gexec
SQL

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin main
  git -C "$APP_DIR" reset --hard origin/main
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo -u "$APP_USER" env $(grep -v '^#' /etc/django-crm.env | xargs) "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" collectstatic --noinput
sudo -u "$APP_USER" env $(grep -v '^#' /etc/django-crm.env | xargs) "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" migrate

cat >/etc/systemd/system/django-crm.service <<EOF
[Unit]
Description=Django CRM Gunicorn service
After=network.target postgresql.service

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/django-crm.env
ExecStart=$APP_DIR/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/nginx/sites-available/django-crm <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 50M;

    location /static/ {
        alias $APP_DIR/staticfiles/;
    }

    location /media/ {
        alias $APP_DIR/media/;
    }

    location / {
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_pass http://127.0.0.1:8000;
    }
}
EOF

ln -sf /etc/nginx/sites-available/django-crm /etc/nginx/sites-enabled/django-crm
rm -f /etc/nginx/sites-enabled/default
nginx -t

systemctl daemon-reload
systemctl enable --now django-crm
systemctl restart django-crm
systemctl reload nginx

echo "Django CRM is installed. Check: systemctl status django-crm"
