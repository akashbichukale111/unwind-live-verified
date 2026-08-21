#!/usr/bin/env bash
#
# Start the Firestore emulator without requiring the gcloud SDK.
#
# `gcloud emulators firestore start` is the documented path, but gcloud is a
# large install and is not present in every environment this repo has to run in.
# The emulator itself is a single jar published to a public bucket, so this
# script fetches it once into .cache/ and runs it directly on the JVM.
#
# Requires: Java 11 or newer.

set -euo pipefail

EMULATOR_VERSION="${FIRESTORE_EMULATOR_VERSION:-1.19.8}"
HOST_PORT="${FIRESTORE_EMULATOR_HOST:-localhost:8080}"
PORT="${HOST_PORT##*:}"
CACHE_DIR="${UNWIND_CACHE_DIR:-.cache}"
JAR="${CACHE_DIR}/cloud-firestore-emulator-v${EMULATOR_VERSION}.jar"
URL="https://storage.googleapis.com/firebase-preview-drop/emulator/cloud-firestore-emulator-v${EMULATOR_VERSION}.jar"

if ! command -v java >/dev/null 2>&1; then
  echo "java not found. The Firestore emulator needs a JVM (Java 11+)." >&2
  exit 2
fi

mkdir -p "${CACHE_DIR}"
if [[ ! -f "${JAR}" ]]; then
  echo "==> Fetching Firestore emulator v${EMULATOR_VERSION}"
  curl -fsSL "${URL}" -o "${JAR}.partial"
  mv "${JAR}.partial" "${JAR}"
fi

echo "==> Firestore emulator listening on ${HOST_PORT}"
echo "    export FIRESTORE_EMULATOR_HOST=${HOST_PORT}"
exec java -jar "${JAR}" --host=127.0.0.1 --port="${PORT}"
