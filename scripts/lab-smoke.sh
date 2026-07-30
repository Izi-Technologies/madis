#!/usr/bin/env bash
# Local or Docker IMS lab smoke helpers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd="${1:-help}"

case "$cmd" in
  unit)
    ./scripts/test.sh tests
    python3 -m unittest discover -s lab -p 'test_*.py'
    python3 -m unittest discover -s media -p 'test_*.py'
    echo "lab-smoke unit: ok"
    ;;
  e2e)
    # Requires Mako 0.5.0 and a built Madis binary.
    MAKO_BIN="${MAKO_BIN:-mako}"
    case "$($MAKO_BIN version 2>/dev/null || true)" in
      *0.5.0*) ;;
      *) echo "Mako 0.5.0 required for e2e (found: $($MAKO_BIN version 2>/dev/null || unknown))" >&2; exit 1 ;;
    esac
    MADIS_OUT="${MADIS_BIN:-$ROOT/build/madis}"
    if [[ ! -x "$MADIS_OUT" ]]; then
      mkdir -p "$(dirname "$MADIS_OUT")"
      "$ROOT/scripts/build-native.sh" main.mko "$MADIS_OUT"
    fi
    export IMS_END_TO_END=1
    export MADIS_BIN="$MADIS_OUT"
    python3 -m unittest \
      lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_hss_unavailable_fails_closed \
      lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_register_retransmission_replays_response \
      lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_two_subscribers_register_call_and_clear \
      lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_two_subscribers_cancel_call \
      -v
    echo "lab-smoke e2e: ok"
    ;;
  docker)
    # Build one Madis image first (shared by P/I/S-CSCF) to avoid triple compile OOM.
    echo "Building Madis image (low-memory Mako cargo)..."
    docker compose -f docker-compose.ims-lab.yml build scscf
    docker compose -f docker-compose.ims-lab.yml build hss media client icscf pcscf
    docker compose -f docker-compose.ims-lab.yml up \
      --abort-on-container-exit \
      --exit-code-from client
    ;;
  docker-down)
    docker compose -f docker-compose.ims-lab.yml down -v --remove-orphans || true
    ;;
  mmtel)
    exec python3 lab/mmtel_as.py --seed-json lab/mmtel_seed.json --bind 127.0.0.1 --port "${2:-5090}"
    ;;
  hss)
    # Plaintext Diameter lab HSS on loopback (no secrets committed).
    SEED="${2:-docker/ims-lab/subscribers.json}"
    exec python3 lab/ims_hss.py \
      --seed-json "$SEED" \
      --diameter-host 127.0.0.1 \
      --diameter-port "${DIAMETER_PORT:-3868}" \
      --http-host 127.0.0.1 \
      --http-port "${HSS_HTTP_PORT:-8444}" \
      --allow-plaintext 1
    ;;
  help|*)
    cat <<'EOF'
Usage: scripts/lab-smoke.sh <command>

  unit          Run Mako contract tests + lab/media Python unit tests
  e2e           Build Madis (Mako 0.5.0) + two-subscriber Cx/AKA/INVITE smoke
  docker        Build IMS lab images and run client smoke (needs Docker RAM for Mako cargo)
  docker-down   Tear down IMS lab compose
  mmtel [port]  Run lab MMTel/TAS stub (default 5090)
  hss [seed]    Run lab HSS adapter on loopback (plaintext Diameter)

Docker smoke success ends with the client message about P-/I-/S-CSCF Cx/AKA.
EOF
    ;;
esac
