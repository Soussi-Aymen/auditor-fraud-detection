#!/usr/bin/env bash
# Compose end-to-end: build, upload sample zip, assert SSE findings, tear down.
# Requires Docker Desktop with WSL integration (or native Docker).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

ZIP="${ROOT}/data/Uebungsdaten_Muster_Verpackungen.zip"
if [[ ! -f "$ZIP" ]]; then
  echo "MISSING sample zip: $ZIP" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found — enable Docker Desktop WSL integration, then re-run." >&2
  exit 1
fi

cleanup() {
  docker compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> docker compose up --build -d"
docker compose up --build -d

echo "==> wait for backend health"
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:8000/api/health" >/dev/null; then
    break
  fi
  sleep 2
  if [[ "$i" -eq 60 ]]; then
    echo "backend health timeout" >&2
    docker compose logs backend | tail -80 >&2
    exit 1
  fi
done

echo "==> upload sample zip"
UP="$(curl -sf -F "file=@${ZIP}" "http://127.0.0.1:8000/api/upload")"
JOB_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' <<<"$UP")"
echo "job_id=${JOB_ID}"

echo "==> SSE stream"
SSE="$(curl -sfN "http://127.0.0.1:8000/api/analyze/${JOB_ID}/stream")"
echo "$SSE" | grep -q 'event: finding' || { echo "no finding events" >&2; exit 1; }
echo "$SSE" | grep -q 'event: done' || { echo "no done event" >&2; exit 1; }
echo "$SSE" | grep -q 'event: error' && { echo "stream error" >&2; exit 1; }

FINDING_COUNT="$(echo "$SSE" | grep -c 'event: finding' || true)"
echo "sse_findings=${FINDING_COUNT}"
if [[ "${FINDING_COUNT}" -lt 1 ]]; then
  echo "expected at least one finding" >&2
  exit 1
fi

echo "==> frontend proxy"
curl -sf -o /dev/null "http://127.0.0.1:5173/" || {
  echo "frontend not serving on :5173" >&2
  exit 1
}

echo "COMPOSE_E2E_OK"
