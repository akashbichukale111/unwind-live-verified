#!/usr/bin/env bash
#
# Deploy UNWIND to Cloud Run.
#
# ############################################################################
# [UNVERIFIED] THIS SCRIPT HAS NEVER BEEN RUN.
#
# It was rewritten in Task 6 after a line-by-line review found four defects in
# the previous version (see docs/DEPLOY.md "What was wrong before"). The flags
# below were checked against the CLI surfaces available at review time, but no
# credentialed execution has happened. Until `make deploy-verify <URL>` passes,
# nothing here is proven and there is no deployed URL.
# ############################################################################
#
# WHAT THIS DEPLOYS, AND WHY IT IS NOT `adk deploy`
# -------------------------------------------------
# The product surface is `services/api/main.py` -- FastAPI serving BOTH the
# operator UI (three static files under web/static) and the /api/* endpoints
# from ONE origin. `adk deploy cloud_run` deploys the ADK API server and,
# optionally, the ADK *development* web UI, which its own --help calls
# "for development and testing only -- do not use in production". It would not
# serve web/static at all.
#
# So this deploys the FastAPI app with `gcloud run deploy --source .`, using
# buildpacks and the Procfile at the repository root. The ADK Workflow in
# agents/cascade is still exercised in-process by that app; it does not need a
# separate deployment to be real.

set -euo pipefail

PROJECT_ID="${UNWIND_PROJECT_ID:-}"

# ⚠ CLOUD RUN REGION IS NOT THE VERTEX LOCATION. They are different axes and
# conflating them is the defect that would have broken the first run: the
# verified Vertex location is `global`, which Cloud Run does not accept as a
# region. `global` is a valid Vertex AI location; Cloud Run requires a real
# region such as us-central1. The service talks to Vertex at `global` FROM a
# regional Cloud Run instance, and both values are passed explicitly.
RUN_REGION="${UNWIND_RUN_REGION:-us-central1}"
VERTEX_LOCATION="${UNWIND_VERTEX_LOCATION:-global}"

SERVICE_NAME="${UNWIND_SERVICE_NAME:-unwind}"
RUNTIME_SA="${UNWIND_RUNTIME_SA:-unwind-run}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "UNWIND_PROJECT_ID is not set. Refusing to guess a project." >&2
  exit 2
fi

if [[ "${RUN_REGION}" == "global" ]]; then
  echo "UNWIND_RUN_REGION=global is invalid: Cloud Run has no 'global' region." >&2
  echo "Set a real region (e.g. us-central1). The Vertex location stays 'global'." >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "required binary not found: gcloud" >&2
  exit 2
fi

SA_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> project=${PROJECT_ID} run_region=${RUN_REGION} vertex_location=${VERTEX_LOCATION}"
echo "==> service=${SERVICE_NAME} runtime_sa=${SA_EMAIL}"

echo "==> Enabling the four approved services (and the build service Cloud Run needs)"
gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project "${PROJECT_ID}"

echo "==> Runtime service account (least privilege: three roles, no Owner/Editor)"
gcloud iam service-accounts describe "${SA_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "${RUNTIME_SA}" \
       --display-name="UNWIND Cloud Run runtime" --project "${PROJECT_ID}"

for role in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
  echo "    bound ${role}"
done

# Operator bearer tokens (lib/auth.py:_parse_operator_tokens), wired from
# Secret Manager rather than a plaintext --set-env-vars value. The ONLY name
# that matters here is the environment variable name on the right of the
# `=`: lib/auth.py reads exactly `UNWIND_OPERATOR_TOKENS` and nothing else,
# so a secret bound under any other variable name is invisible to the app
# and every bearer token is rejected with 401 -- silently, because IAM and
# the mount both succeed; only the variable NAME was ever wrong. Optional:
# a deploy with no such secret in this project runs exactly as before, with
# bearer-token auth simply unavailable (IAP or UNWIND_DEV_PRINCIPAL still
# work for local/dev use).
OPERATOR_TOKEN_SECRET="${UNWIND_OPERATOR_TOKEN_SECRET:-unwind-operator-token}"
SECRET_FLAGS=()
if gcloud secrets describe "${OPERATOR_TOKEN_SECRET}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "==> Operator token secret '${OPERATOR_TOKEN_SECRET}' found -- wiring to UNWIND_OPERATOR_TOKENS"
  gcloud secrets add-iam-policy-binding "${OPERATOR_TOKEN_SECRET}" \
    --project "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
  echo "    bound roles/secretmanager.secretAccessor (scoped to this secret only)"
  SECRET_FLAGS=(--set-secrets "UNWIND_OPERATOR_TOKENS=${OPERATOR_TOKEN_SECRET}:latest")
else
  echo "==> No '${OPERATOR_TOKEN_SECRET}' secret in this project -- deploying without bearer-token auth"
fi

echo "==> Pub/Sub topics"
# Topic ids may not contain dots, so lib/config.py's logical names are
# hyphenated on the wire. lib/pubsub.py:_wire_name performs the same mapping;
# the two must stay in step. Verified: `topic.replace(".", "-")`.
for topic in claim-retracted node-rederive node-scored \
             repair-convened obligation-raised unwind-executed; do
  gcloud pubsub topics describe "${topic}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || gcloud pubsub topics create "${topic}" --project "${PROJECT_ID}"
  gcloud pubsub subscriptions describe "${topic}-sub" --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || gcloud pubsub subscriptions create "${topic}-sub" \
         --topic "${topic}" --project "${PROJECT_ID}"
done

echo "==> Cloud Run (source deploy; buildpacks read the Procfile at the repo root)"
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${PROJECT_ID}" \
  --region "${RUN_REGION}" \
  --service-account "${SA_EMAIL}" \
  --allow-unauthenticated \
  --set-env-vars "UNWIND_PROJECT_ID=${PROJECT_ID},UNWIND_VERTEX_LOCATION=${VERTEX_LOCATION},UNWIND_OTEL_CONSOLE=0" \
  "${SECRET_FLAGS[@]}" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 4

URL="$(gcloud run services describe "${SERVICE_NAME}" \
        --project "${PROJECT_ID}" --region "${RUN_REGION}" \
        --format='value(status.url)')"

echo
echo "==> Deployed: ${URL}"
echo "==> NOW PROVE IT COMPUTES, not merely renders:"
echo "      make deploy-verify URL=${URL}"
echo
echo "Firestore rules and composite indexes are NOT deployed by this script."
echo "They need the Firebase CLI -- see docs/DEPLOY.md step 6."
