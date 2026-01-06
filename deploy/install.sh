#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "")"
# Если скрипт запущен через bash <(curl ...) BASH_SOURCE может указывать на /dev/fd/*
if [[ -z "${SCRIPT_DIR}" || "${SCRIPT_DIR}" == "/dev" || "${SCRIPT_DIR}" == "/dev/fd"* ]]; then
  # Разворачиваем репозиторий в /opt/Morpheus по умолчанию
  PROJECT_ROOT="/opt/Morpheus"
else
  PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
ENV_FILE="${PROJECT_ROOT}/.env"
SAMPLE_ENV="${PROJECT_ROOT}/env.sample"
CERT_DIR="${PROJECT_ROOT}/deploy/certs"
NGINX_CONF="${PROJECT_ROOT}/deploy/nginx/default.conf"

function require_root() {
  if [[ "$EUID" -ne 0 ]]; then
    echo "Run as root (sudo)." >&2
    exit 1
  fi
}

function install_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "[*] Installing Docker..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list >/dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
  else
    echo "[*] Docker already installed."
  fi
}

function ensure_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${SAMPLE_ENV}" ]]; then
      echo "[*] Creating .env from sample. Please edit values after installation."
      cp "${SAMPLE_ENV}" "${ENV_FILE}"
    else
      echo "[!] env.sample not found in ${PROJECT_ROOT}, creating minimal .env"
      cat > "${ENV_FILE}" <<EOF
POSTGRES_USER=morpheus
POSTGRES_PASSWORD=$(openssl rand -hex 12)
POSTGRES_DB=morpheus
HTTP_PORT=80
HTTPS_PORT=443
SECRET_KEY=$(openssl rand -hex 32)
ACCESS_TOKEN_EXPIRE_MINUTES=1440
TELEGRAM_BOT_TOKEN=
BOT_ADMINS=
ANYPAY_PROJECT_ID=
ANYPAY_API_ID=
ANYPAY_API_KEY=
ANYPAY_CURRENCY=RUB
ANYPAY_METHOD=card
ANYPAY_SUCCESS_URL=http://localhost/success
ANYPAY_FAIL_URL=http://localhost/fail
PUBLIC_BASE_URL=https://localhost
EOF
    fi
  else
    echo "[*] .env already exists, skipping copy."
  fi
}

function generate_certs() {
  mkdir -p "${CERT_DIR}"
  local key="${CERT_DIR}/morpheus.key"
  local crt="${CERT_DIR}/morpheus.crt"
  if [[ -f "${key}" && -f "${crt}" ]]; then
    echo "[*] TLS certificates already present."
    return
  fi
  echo "[*] Generating self-signed TLS certificate..."
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 -sha256 \
    -keyout "${key}" \
    -out "${crt}" \
    -subj "/C=RU/ST=NA/L=NA/O=Morpheus/OU=Dev/CN=localhost"
  chmod 600 "${key}"
}

function write_nginx_conf() {
  mkdir -p "$(dirname "${NGINX_CONF}")"
  cat > "${NGINX_CONF}" <<'EOF'
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/certs/morpheus.crt;
    ssl_certificate_key /etc/nginx/certs/morpheus.key;

    client_max_body_size 200M;

    location / {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /uploads/ {
        alias /app/uploads/;
        autoindex on;
    }
}
EOF
}

function start_stack() {
  echo "[*] Building and starting services..."
  docker compose -f "${PROJECT_ROOT}/docker-compose.yml" up -d --build
}

require_root
install_docker
ensure_env
generate_certs
write_nginx_conf
start_stack

echo ""
echo "Installation complete."
echo "Edit ${ENV_FILE} to set TELEGRAM_BOT_TOKEN and anypay keys, then run:"
echo "  sudo docker compose restart api"

