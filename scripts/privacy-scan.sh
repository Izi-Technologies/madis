#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

files=$(
  git ls-files \
    ':!:*.png' ':!:*.jpg' ':!:*.jpeg' ':!:*.gif' ':!:*.ico' ':!:*.pdf' \
    ':!:*.der' ':!:*.crt' ':!:*.key' ':!:*.pem'
)

fail=0

scan_regex() {
  local label="$1"
  local regex="$2"
  local matches
  matches=$(printf '%s\n' "$files" | xargs grep -nEI "$regex" 2>/dev/null || true)
  if [[ -n "$matches" ]]; then
    printf 'privacy-scan: %s\n%s\n' "$label" "$matches" >&2
    fail=1
  fi
}

key_re='BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY|PRIVATE KEY-{5}'
scan_regex "possible private key material" "$key_re"
scan_regex "possible hard-coded cloud credential" 'A[K]IA[0-9A-Z]{16}|A[S]IA[0-9A-Z]{16}|[a]ws_secret_access_key|[a]ws_access_key_id'

sensitive_files=$(git ls-files | grep -E '(^|/)(\.env(\..*)?|madis\.env|.*\.(pem|key))$' | grep -vE '(^|/)[^/]+\.env\.example$|(^|/)madis\.env\.example$' || true)
if [[ -n "$sensitive_files" ]]; then
  printf 'privacy-scan: sensitive filename is tracked\n%s\n' "$sensitive_files" >&2
  fail=1
fi

if [[ "${MADIS_PRIVACY_SCAN_IPS:-0}" == "1" ]]; then
  scan_regex "possible IPv4 address" '(^|[^0-9])([0-9]{1,3}\.){3}[0-9]{1,3}([^0-9]|$)'
fi

if [[ -f .privacy-denylist.local ]]; then
  while IFS= read -r term; do
    [[ -z "$term" || "$term" =~ ^[[:space:]]*# ]] && continue
    matches=$(printf '%s\n' "$files" | xargs grep -nIF "$term" 2>/dev/null || true)
    if [[ -n "$matches" ]]; then
      printf 'privacy-scan: local denylist term matched\n%s\n' "$matches" >&2
      fail=1
    fi
  done < .privacy-denylist.local
fi

if [[ "$fail" -ne 0 ]]; then
  echo "privacy-scan: failed" >&2
  exit 1
fi

echo "privacy-scan: ok"
