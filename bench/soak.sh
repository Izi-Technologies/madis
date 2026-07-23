#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNS=${SOAK_RUNS:-3}
CALLS=${SOAK_CALLS:-500}
RATE=${SOAK_RATE:-500}
CONCURRENCY=${SOAK_CONCURRENCY:-250}
WORKERS=${SOAK_WORKERS:-4}

i=1
while [ "$i" -le "$RUNS" ]; do
    echo "Soak run $i/$RUNS: rate=$RATE calls=$CALLS concurrency=$CONCURRENCY workers=$WORKERS"
    RATE="$RATE" CALLS="$CALLS" CONCURRENCY="$CONCURRENCY" WORKERS="$WORKERS" \
        STATS="${TMPDIR:-/tmp}/mako-soak-$i.csv" "$ROOT/bench/benchmark.sh"
    i=$((i + 1))
done

echo "SIP soak: $RUNS runs completed"
