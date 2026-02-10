#!/usr/bin/env bash
set -euo pipefail

# Pause Cloud Scheduler after verifying the VM cron works.
# Does NOT delete anything — keeps Cloud Run Job + Scheduler for rollback.
#
# Usage:
#   ./scripts/vm/pause_cloud_run.sh

PROJECT_ID="${PROJECT_ID:-notorios}"
REGION="${REGION:-us-central1}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-metrics-report-daily}"

gcloud config set project "${PROJECT_ID}" >/dev/null

echo "Pausing Cloud Scheduler job: ${SCHEDULER_JOB_NAME}"
gcloud scheduler jobs pause "${SCHEDULER_JOB_NAME}" --location="${REGION}"

echo "Done. Cloud Scheduler paused (Cloud Run Job preserved for rollback)."
echo ""
echo "To resume if needed:"
echo "  gcloud scheduler jobs resume ${SCHEDULER_JOB_NAME} --location=${REGION}"
