#!/usr/bin/env bash
#
# Run the UNWIND API locally against the Firestore emulator and the in-process
# Pub/Sub shim. This is the whole local stack: no GCP account required.

set -euo pipefail

export FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-localhost:8080}"
export UNWIND_PUBSUB_LOCAL="${UNWIND_PUBSUB_LOCAL:-1}"
export UNWIND_PROJECT_ID="${UNWIND_PROJECT_ID:-unwind-local}"

if ! curl -fsS "http://${FIRESTORE_EMULATOR_HOST}/" >/dev/null 2>&1; then
  echo "Firestore emulator is not answering on ${FIRESTORE_EMULATOR_HOST}." >&2
  echo "Start it in another terminal first:  make emulator" >&2
  exit 2
fi

echo "==> Firestore emulator: ${FIRESTORE_EMULATOR_HOST}"
echo "==> Pub/Sub: in-process shim"
echo "==> API: http://127.0.0.1:8000  (try /api/healthz)"

exec .venv/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8000 --reload
