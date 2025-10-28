#!/usr/bin/env bash
# ci/test_failover.sh
# Verify Blue->Green failover behavior with Nginx as a reverse proxy.
# Usage: from repo root, with docker-compose up -d already run and .env set.

set -euo pipefail

BASE_URL="http://localhost:8080"
BLUE_DIRECT="http://localhost:8081"
GREEN_DIRECT="http://localhost:8082"
TIMEOUT_CURL="--max-time 5"

# helper: get header value
get_header() {
  local url=$1
  local header=$2
  curl -sS ${TIMEOUT_CURL} -D - -o /dev/null "$url" | awk -v h="$header:" 'tolower($0) ~ tolower(h) {sub(/^[ \t]*/,"",$0); print substr($0, index($0,":")+2); exit}'
}

# Wait for services to be ready
echo "Waiting for Nginx to be reachable..."
for i in $(seq 1 20); do
  if curl -sS ${TIMEOUT_CURL} ${BASE_URL}/version >/dev/null 2>&1; then
    echo "Nginx reachable"
    break
  fi
  sleep 1
done

# Active pool expected by default
EXPECTED_POOL="blue"
echo "Expected active pool (default): $EXPECTED_POOL"

# Baseline: verify all 8 requests hit Blue
echo "Baseline: sending 8 requests to $BASE_URL/version"
baseline_ok=true
for i in $(seq 1 8); do
  pool=$(get_header ${BASE_URL}/version "X-App-Pool" | tr -d '\r') || pool="unknown"
if [ "$pool" != "$EXPECTED_POOL" ]; then
  echo "Baseline failure: request $i returned X-App-Pool='$pool' expected '$EXPECTED_POOL'"
  baseline_ok=false
fi
done
if [ "$baseline_ok" != "true" ]; then
  echo "Baseline checks failed. Aborting."
  exit 1
fi
echo "Baseline OK: all requests served by Blue"

# Trigger chaos on Blue (primary)
echo "Triggering chaos on Blue (primary)"
curl -sS -X POST ${TIMEOUT_CURL} "$BLUE_DIRECT/chaos/start?mode=error" || true

# Test failover via Nginx
echo "Testing failover: send 50 requests over ~8s"
TOTAL=50
SLEEP_BETWEEN=0.16  # ~8s total
count_200=0
count_green=0
count_non200=0

for i in $(seq 1 $TOTAL); do
  http_code=$(curl -sS -D /tmp/tmpheaders -o /tmp/tmpbody -w "%{http_code}" ${BASE_URL}/version || echo "000")
  
  if [ "$http_code" = "200" ]; then
    count_200=$((count_200+1))
    pool=$(awk '/^X-App-Pool:/ {print $2; exit}' /tmp/tmpheaders | tr -d '\r')
    if [ -z "$pool" ]; then
      pool=$(get_header ${BASE_URL}/version "X-App-Pool")
    fi
    if [ "$pool" = "green" ]; then
      count_green=$((count_green+1))
    fi
  else
    count_non200=$((count_non200+1))
  fi
  sleep $SLEEP_BETWEEN
done

echo "Results: total requests=$TOTAL, 200s=$count_200, non-200s=$count_non200, green_responses=$count_green"

# Evaluate pass criteria
if [ "$count_non200" -ne 0 ]; then
  echo "FAIL: observed $count_non200 non-200 responses (expected 0)."
  exit 1
fi

pct=$((100 * count_green / count_200))
if [ "$pct" -lt 95 ]; then
  echo "FAIL: only ${pct}% of successful requests served by Green (need >=95%)."
  exit 1
fi

echo "PASS: Failover successful. ${pct}% of requests served by Green with 0 non-200s."

# Stop chaos on Blue
echo "Stopping chaos on Blue"
curl -sS -X POST ${TIMEOUT_CURL} "$BLUE_DIRECT/chaos/stop" || true

exit 0
