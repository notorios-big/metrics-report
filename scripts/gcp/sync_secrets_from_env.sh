#!/usr/bin/env bash
set -euo pipefail

# Syncs selected keys from a local .env file into Secret Manager.
# - Secrets are created as: LEJUSTE_<KEY>
# - Values are never printed to stdout.
#
# Usage:
#   PROJECT_ID=notorios ./scripts/gcp/sync_secrets_from_env.sh .env
#
# Note: this only uploads secrets (tokens/keys). Non-secret config stays as env vars.

PROJECT_ID="${PROJECT_ID:-}"
ENV_FILE="${1:-.env}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Missing env var: PROJECT_ID" >&2
  exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Env file not found: ${ENV_FILE}" >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}" >/dev/null

keys=(
  SHOPIFY_ACCESS_TOKEN
  META_ACCESS_TOKEN
  KLAVIYO_PRIVATE_KEY
  GOOGLE_ADS_DEVELOPER_TOKEN
  GOOGLE_ADS_OAUTH_CLIENT_ID
  GOOGLE_ADS_OAUTH_CLIENT_SECRET
  GOOGLE_ADS_OAUTH_REFRESH_TOKEN
)

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

for key in "${keys[@]}"; do
  value="$(
    python3 - "$ENV_FILE" "$key" <<'PY'
import re
import sys

path, key = sys.argv[1], sys.argv[2]
pat = re.compile(rf'^\s*(?:LEJUSTE_)?{re.escape(key)}\s*=\s*(.*)\s*$')

with open(path, "r", encoding="utf-8") as f:
    for line in f:
        if line.lstrip().startswith("#") or not line.strip():
            continue
        m = pat.match(line)
        if not m:
            continue
        raw = m.group(1).strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        print(raw)
        raise SystemExit(0)
raise SystemExit(2)
PY
  )" || true

  if [[ -z "${value}" ]]; then
    echo "Skip (empty/missing): ${key}" >&2
    continue
  fi

  secret="LEJUSTE_${key}"
  if ! gcloud secrets describe "${secret}" >/dev/null 2>&1; then
    echo "Creating secret: ${secret}" >&2
    gcloud secrets create "${secret}" --replication-policy=automatic >/dev/null
  fi

  printf '%s' "${value}" >"$tmp"
  echo "Adding new version: ${secret}" >&2
  gcloud secrets versions add "${secret}" --data-file="$tmp" >/dev/null
done

echo "Done. Next: map secrets to the Cloud Run Job with --set-secrets ..." >&2

