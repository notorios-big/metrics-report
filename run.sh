#!/usr/bin/env bash
set -euo pipefail

# Wrapper script for running metrics-report on the langgraph VM.
# Fetches secrets from GCP Secret Manager and runs the pipeline.
#
# Usage:
#   /opt/metrics-report/run.sh
#
# Cron (9:00 AM Chile, user sam):
#   0 9 * * * /opt/metrics-report/run.sh >> /var/log/metrics-report.log 2>&1

PROJECT_ID="${PROJECT_ID:-notorios}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== metrics-report $(date -Iseconds) ==="

# --- Fetch secrets from Secret Manager ---
secrets=(
  LEJUSTE_SHOPIFY_ACCESS_TOKEN
  LEJUSTE_META_ACCESS_TOKEN
  LEJUSTE_KLAVIYO_PRIVATE_KEY
  LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN
  LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID
  LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET
  LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN
)

for secret in "${secrets[@]}"; do
  value="$(gcloud secrets versions access latest --secret="${secret}" --project="${PROJECT_ID}" 2>/dev/null)" || {
    echo "ERROR: failed to read secret ${secret}" >&2
    exit 1
  }
  export "${secret}=${value}"
done

# --- Point to service-account credentials for Google Sheets ---
if [[ -f "${SCRIPT_DIR}/gs_cred.json" ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${SCRIPT_DIR}/gs_cred.json"
fi

# --- Run the pipeline ---
cd "${SCRIPT_DIR}"
"${SCRIPT_DIR}/.venv/bin/python" -m metrics_report

echo "=== done $(date -Iseconds) ==="
