#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-}"
JOB_NAME="${JOB_NAME:-metrics-report}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-metrics-report-daily}"
SCHEDULE="${SCHEDULE:-0 9 * * *}"
TIME_ZONE="${TIME_ZONE:-America/Santiago}"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA_EMAIL:-}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Missing env var: PROJECT_ID" >&2
  exit 1
fi
if [[ -z "$REGION" ]]; then
  echo "Missing env var: REGION" >&2
  exit 1
fi
if [[ -z "$SCHEDULER_SA_EMAIL" ]]; then
  echo "Missing env var: SCHEDULER_SA_EMAIL (Cloud Scheduler OAuth SA)" >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}" >/dev/null

URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location "${REGION}" >/dev/null 2>&1; then
  echo "Updating Cloud Scheduler job: ${SCHEDULER_JOB_NAME}"
  gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
    --location "${REGION}" \
    --schedule "${SCHEDULE}" \
    --time-zone "${TIME_ZONE}" \
    --uri "${URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA_EMAIL}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --message-body "{}"
else
  echo "Creating Cloud Scheduler job: ${SCHEDULER_JOB_NAME}"
  gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
    --location "${REGION}" \
    --schedule "${SCHEDULE}" \
    --time-zone "${TIME_ZONE}" \
    --uri "${URI}" \
    --http-method POST \
    --oauth-service-account-email "${SCHEDULER_SA_EMAIL}" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --message-body "{}"
fi

echo "Done. You can test by running: gcloud run jobs execute ${JOB_NAME} --region ${REGION} --wait"

