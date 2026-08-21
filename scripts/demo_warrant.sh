#!/usr/bin/env bash
# Stages Card 0's demo moment end-to-end against a real Firestore emulator:
#
#   1. checks (does not start) the emulator -- `make emulator` in another
#      terminal, same as every other tower/ integration test in this repo
#   2. runs scripts/demo_warrant.py: ACT 1 (BURN drops a bar below the
#      routing line, next case of that class routes to a human) and ACT 2
#      (a cold-start agent earns its first delegation live, on camera)
#   3. runs scripts/rederive_warrant.py: proves the balances both acts just
#      produced are bit-equal to a fresh fold of the log -- SYNTHETIC seed
#      history and this run's EARNED events fold through the identical path
#
# Usage:
#   make emulator            # one terminal
#   bash scripts/demo_warrant.sh   # another

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

HOST="${FIRESTORE_EMULATOR_HOST:-localhost:8080}"
HOSTNAME="${HOST%%:*}"
PORT="${HOST##*:}"

if ! (exec 3<>"/dev/tcp/${HOSTNAME}/${PORT}") 2>/dev/null; then
  echo "Firestore emulator is not answering on ${HOST}." >&2
  echo "Start it first, in another terminal:  make emulator" >&2
  exit 2
fi
exec 3>&- 3<&- || true

export FIRESTORE_EMULATOR_HOST="$HOST"
export UNWIND_PROJECT_ID="${UNWIND_PROJECT_ID:-unwind-warrant-demo}"
export UNWIND_COUNTERSIGN_SIMULATED="${UNWIND_COUNTERSIGN_SIMULATED:-1}"
export UNWIND_OTEL_CONSOLE=0

PY="${PY:-.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

"$PY" scripts/demo_warrant.py
echo
"$PY" scripts/rederive_warrant.py
