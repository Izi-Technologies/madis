#!/bin/sh
set -eu

umask 077
mkdir -p /certs
# The cert volume is persistent across lab runs; regenerate when the runtime
# certificate is missing or expires within the hour instead of reusing a
# stale one.
needs_cert=0
if [ ! -s /certs/hss.crt ] || [ ! -s /certs/hss.key ]; then
    needs_cert=1
elif ! openssl x509 -in /certs/hss.crt -noout -checkend 3600 >/dev/null 2>&1; then
    needs_cert=1
fi
if [ "$needs_cert" -eq 1 ]; then
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout /certs/hss.key \
        -out /certs/hss.crt \
        -days 1 \
        -subj '/CN=hss' \
        -addext 'subjectAltName=DNS:hss,IP:172.30.0.2'
fi

chmod 0644 /certs/hss.crt
chmod 0600 /certs/hss.key

exec python3 /app/lab/ims_hss.py \
    --seed-json /app/subscribers.json \
    --diameter-host 0.0.0.0 \
    --diameter-port 3868 \
    --diameter-cert /certs/hss.crt \
    --diameter-key /certs/hss.key \
  --http-host 0.0.0.0 \
  --http-port 8080 \
  --http-cert /certs/hss.crt \
  --http-key /certs/hss.key \
  --http-token ims-docker-hss-http-token-123456 \
  --origin-host hss \
    --origin-realm example.com
