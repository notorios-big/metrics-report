#!/usr/bin/env bash
set -euo pipefail

# Setup metrics-report on the langgraph VM.
# Run this script ON the VM as user sam (or with sudo for the /opt parts).
#
# Prerequisites:
#   - git, python3.12, python3.12-venv installed
#   - gcloud CLI authenticated with access to Secret Manager
#   - gs_cred.json copied to /opt/metrics-report/gs_cred.json
#
# Usage:
#   sudo bash scripts/vm/setup.sh

INSTALL_DIR="/opt/metrics-report"
REPO_URL="https://github.com/notorios-big/metrics-report.git"
CRON_USER="sam"
LOG_FILE="/var/log/metrics-report.log"

echo "=== Setting up metrics-report at ${INSTALL_DIR} ==="

# --- 1. Clone or update repo ---
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  echo "Repo already exists, pulling latest..."
  git -C "${INSTALL_DIR}" pull --ff-only
else
  echo "Cloning repo..."
  sudo mkdir -p "${INSTALL_DIR}"
  sudo chown "${CRON_USER}:${CRON_USER}" "${INSTALL_DIR}"
  git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

# --- 2. Create virtualenv + install deps ---
if [[ ! -d "${INSTALL_DIR}/.venv" ]]; then
  echo "Creating virtualenv..."
  python3.12 -m venv "${INSTALL_DIR}/.venv"
fi

echo "Installing dependencies..."
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip -q
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q

# --- 3. Verify gs_cred.json ---
if [[ ! -f "${INSTALL_DIR}/gs_cred.json" ]]; then
  echo ""
  echo "WARNING: gs_cred.json not found at ${INSTALL_DIR}/gs_cred.json"
  echo "Copy it manually: scp gs_cred.json langgraph:${INSTALL_DIR}/gs_cred.json"
  echo ""
fi

# --- 4. Create log file ---
sudo touch "${LOG_FILE}"
sudo chown "${CRON_USER}:${CRON_USER}" "${LOG_FILE}"

# --- 5. Make run.sh executable ---
chmod +x "${INSTALL_DIR}/run.sh"

# --- 6. Install cron job ---
CRON_LINE="0 9 * * * ${INSTALL_DIR}/run.sh >> ${LOG_FILE} 2>&1"
existing_crontab=$(crontab -u "${CRON_USER}" -l 2>/dev/null || true)

if echo "${existing_crontab}" | grep -qF "metrics-report/run.sh"; then
  echo "Cron job already exists, skipping."
else
  echo "Installing cron job for user ${CRON_USER}..."
  (echo "${existing_crontab}"; echo "${CRON_LINE}") | crontab -u "${CRON_USER}" -
  echo "Cron installed: ${CRON_LINE}"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy gs_cred.json if not done yet:"
echo "     scp gs_cred.json langgraph:${INSTALL_DIR}/gs_cred.json"
echo "  2. Test manually:"
echo "     ${INSTALL_DIR}/run.sh"
echo "  3. Check logs:"
echo "     tail -f ${LOG_FILE}"
echo "  4. After verifying, pause Cloud Scheduler:"
echo "     gcloud scheduler jobs pause metrics-report-daily --location=us-central1"
