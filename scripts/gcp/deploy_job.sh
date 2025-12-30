#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-}"
JOB_NAME="${JOB_NAME:-metrics-report}"
IMAGE="${IMAGE:-}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Missing env var: PROJECT_ID" >&2
  exit 1
fi
if [[ -z "$REGION" ]]; then
  echo "Missing env var: REGION" >&2
  exit 1
fi
if [[ -z "$IMAGE" ]]; then
  IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}"
fi
if [[ -z "$SERVICE_ACCOUNT_EMAIL" ]]; then
  echo "Missing env var: SERVICE_ACCOUNT_EMAIL (Cloud Run Job identity)" >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud config set run/region "${REGION}" >/dev/null

echo "Building image: ${IMAGE}"
gcloud builds submit --tag "${IMAGE}" .

if gcloud run jobs describe "${JOB_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  echo "Updating Cloud Run Job: ${JOB_NAME}"
  gcloud run jobs update "${JOB_NAME}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --service-account "${SERVICE_ACCOUNT_EMAIL}"
else
  echo "Creating Cloud Run Job: ${JOB_NAME}"
  gcloud run jobs create "${JOB_NAME}" \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --service-account "${SERVICE_ACCOUNT_EMAIL}"
fi

echo "Done. Next: set env vars / secrets with gcloud run jobs update ${JOB_NAME} --set-env-vars ... --set-secrets ..."

