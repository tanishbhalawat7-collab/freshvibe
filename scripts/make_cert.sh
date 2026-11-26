#!/usr/bin/env bash
# Self-signed HTTPS certificate for LAN use (browsers will ask you to accept it once).
# Prefer `mkcert` (https://github.com/FiloSottile/mkcert) for a trusted local cert.
set -e
cd "$(dirname "$0")/.."
mkdir -p certs
IP=${1:-$(hostname -I 2>/dev/null | awk '{print $1}')}
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=freshvibe.local" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:${IP:-127.0.0.1}"
echo "Add to .env:  SSL_CERTFILE=../certs/cert.pem  SSL_KEYFILE=../certs/key.pem  HOST=0.0.0.0"
