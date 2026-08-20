#!/usr/bin/env bash
set -euo pipefail

: "${MAF_BASE_URL:?set MAF_BASE_URL}"
: "${SIP_MAF_API_TOKEN:?set SIP_MAF_API_TOKEN}"
: "${MAF_SMOKE_TO:?set MAF_SMOKE_TO, for example sip:+15551234567@carrier.example:5060}"

call_id="${MAF_SMOKE_CALL_ID:-maf-smoke-$(date +%s)-$$}"
from_uri="${MAF_SMOKE_FROM:-sip:madis-smoke@example.invalid}"
idem="${MAF_SMOKE_IDEMPOTENCY_KEY:-smoke-$call_id}"

body=$(printf '{"call_id":"%s","from":"%s","to":"%s","application_data":{"purpose":"maf-carrier-smoke"}}' \
  "$call_id" "$from_uri" "$MAF_SMOKE_TO")

code=$(curl -fsS -o /tmp/madis-maf-carrier-smoke.json -w '%{http_code}' \
  -X POST "$MAF_BASE_URL/api/v1/maf/calls" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $idem" \
  --data "$body")

printf 'http_status=%s\ncall_id=%s\nresponse=/tmp/madis-maf-carrier-smoke.json\n' "$code" "$call_id"

if [[ "$code" != "202" && "$code" != "200" ]]; then
  exit 1
fi
