#!/bin/bash
# Upload this file as the cloud-init script in OCI Console.
# For Oracle Linux 9 on VM.Standard.A1.Flex. Never add secrets to this file.
set -Eeuo pipefail

readonly REPO_URL="https://github.com/karaware/receipt-ocr.git"
readonly REPO_REF="main"
readonly APP_USER="receipt-ocr"
readonly APP_GROUP="receipt-ocr"
readonly CODEX_USER="receipt-ocr-codex"
readonly CODEX_GROUP="receipt-ocr-codex"
readonly SPOOL_GROUP="receipt-ocr-spool"
readonly APP_DIR="/opt/receipt-ocr"
readonly CONFIG_DIR="/etc/receipt-ocr-poc"
readonly STATE_DIR="/var/lib/receipt-ocr-poc"
readonly CODEX_STATE_DIR="/var/lib/receipt-ocr-codex"
readonly COMPLETE_MARKER="${STATE_DIR}/bootstrap-complete"

exec > >(tee -a /var/log/receipt-ocr-cloud-init.log) 2>&1
echo "[$(date --iso-8601=seconds)] receipt-ocr PoC bootstrap started"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must run as root" >&2
  exit 1
fi

# A1.Flex is aarch64. Fail early if the wrong shape or image was selected.
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Expected aarch64 for VM.Standard.A1.Flex, got $(uname -m)" >&2
  exit 1
fi

source /etc/os-release
if [[ "${ID:-}" != "ol" || "${VERSION_ID%%.*}" != "9" ]]; then
  echo "Expected Oracle Linux 9, got ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi

timedatectl set-timezone Asia/Tokyo

dnf -y update
dnf -y install \
  bubblewrap \
  ca-certificates \
  curl \
  gcc \
  git \
  libffi-devel \
  openssl-devel \
  python3 \
  python3-devel \
  python3-pip \
  jq
update-ca-trust

if ! getent group "${APP_GROUP}" >/dev/null; then
  groupadd --system "${APP_GROUP}"
fi
if ! getent group "${CODEX_GROUP}" >/dev/null; then
  groupadd --system "${CODEX_GROUP}"
fi
if ! getent group "${SPOOL_GROUP}" >/dev/null; then
  groupadd --system "${SPOOL_GROUP}"
fi
if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${APP_GROUP}" \
    --home-dir "${APP_DIR}" \
    --shell /sbin/nologin \
    "${APP_USER}"
fi
if ! id "${CODEX_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${CODEX_GROUP}" \
    --groups "${APP_GROUP},${SPOOL_GROUP}" \
    --home-dir "${CODEX_STATE_DIR}" \
    --shell /sbin/nologin \
    "${CODEX_USER}"
fi
usermod -a -G "${SPOOL_GROUP}" "${APP_USER}"

install -d -o root -g "${APP_GROUP}" -m 0750 "${CONFIG_DIR}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0700 "${CONFIG_DIR}/secrets"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${STATE_DIR}" "${STATE_DIR}/work"
install -d -o root -g "${SPOOL_GROUP}" -m 2770 "${STATE_DIR}/llm-spool"
for directory in pending running completed unresolved; do
  install -d -o root -g "${SPOOL_GROUP}" -m 2770 "${STATE_DIR}/llm-spool/${directory}"
done
install -d -o "${CODEX_USER}" -g "${CODEX_GROUP}" -m 0700 "${CODEX_STATE_DIR}" "${CODEX_STATE_DIR}/.codex"
cat >"${CODEX_STATE_DIR}/.codex/config.toml" <<'EOF'
cli_auth_credentials_store = "file"
EOF
chown "${CODEX_USER}:${CODEX_GROUP}" "${CODEX_STATE_DIR}/.codex/config.toml"
chmod 0600 "${CODEX_STATE_DIR}/.codex/config.toml"

if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --prune origin
  git -C "${APP_DIR}" checkout "${REPO_REF}"
  git -C "${APP_DIR}" pull --ff-only origin "${REPO_REF}"
elif [[ -e "${APP_DIR}" ]]; then
  echo "${APP_DIR} already exists but is not a Git checkout; refusing to overwrite it" >&2
  exit 1
else
  git clone --branch "${REPO_REF}" --single-branch "${REPO_URL}" "${APP_DIR}"
fi

# Do not accept an incomplete deployment when the PoC code was not pushed.
for required in \
  deploy/oci/receipt-ocr-poc.service \
  deploy/oci/receipt-ocr-poc.timer \
  deploy/oci/receipt-ocr-llm.service \
  deploy/oci/receipt-ocr-llm.timer \
  deploy/oci/receipt-ocr-llm-health.service \
  deploy/oci/receipt-ocr-llm-health.timer \
  deploy/oci/config.example.env \
  deploy/oci/config.poc.example.json \
  schema/receipt-llm-result-v1.json \
  src/receipt_ocr/cloud_worker.py \
  src/receipt_ocr/llm_worker.py; do
  if [[ ! -f "${APP_DIR}/${required}" ]]; then
    echo "Required file is missing from ${REPO_REF}: ${required}" >&2
    echo "Commit and push the OCI PoC implementation, then recreate the VM." >&2
    exit 1
  fi
done

chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${APP_USER}" env PIP_NO_CACHE_DIR=1 "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
sudo -u "${APP_USER}" env PIP_NO_CACHE_DIR=1 "${APP_DIR}/.venv/bin/python" -m pip install -e "${APP_DIR}"

# Install the official standalone Codex CLI for Linux aarch64 into the isolated user's home.
sudo -u "${CODEX_USER}" env \
  HOME="${CODEX_STATE_DIR}" \
  CODEX_HOME="${CODEX_STATE_DIR}/.codex" \
  CODEX_NON_INTERACTIVE=1 \
  /bin/bash -c 'curl -fsSL https://chatgpt.com/codex/install.sh | sh'

install -o root -g "${APP_GROUP}" -m 0640 \
  "${APP_DIR}/deploy/oci/config.example.env" \
  "${CONFIG_DIR}/config.env.example"

if [[ ! -f "${CONFIG_DIR}/config.json" ]]; then
  install -o root -g "${APP_GROUP}" -m 0640 \
    "${APP_DIR}/deploy/oci/config.poc.example.json" \
    "${CONFIG_DIR}/config.json.example"
fi

install -o root -g root -m 0644 \
  "${APP_DIR}/deploy/oci/receipt-ocr-poc.service" \
  /etc/systemd/system/receipt-ocr-poc.service
install -o root -g root -m 0644 \
  "${APP_DIR}/deploy/oci/receipt-ocr-poc.timer" \
  /etc/systemd/system/receipt-ocr-poc.timer
for unit in \
  receipt-ocr-llm.service \
  receipt-ocr-llm.timer \
  receipt-ocr-llm-health.service \
  receipt-ocr-llm-health.timer; do
  install -o root -g root -m 0644 \
    "${APP_DIR}/deploy/oci/${unit}" \
    "/etc/systemd/system/${unit}"
done

# Keep public-key login and disable password and root SSH login.
install -d -o root -g root -m 0755 /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/60-receipt-ocr-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
sshd -t
systemctl reload sshd

systemctl daemon-reload
# Keep the timer disabled until credentials and configuration are installed.
systemctl disable --now receipt-ocr-poc.timer 2>/dev/null || true
systemctl disable --now receipt-ocr-llm.timer receipt-ocr-llm-health.timer 2>/dev/null || true

sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m unittest discover -s "${APP_DIR}/tests"

cat >"${STATE_DIR}/NEXT_STEPS.txt" <<'EOF'
Bootstrap completed. The worker is intentionally disabled.
1. Create /etc/receipt-ocr-poc/config.env from config.env.example.
2. Create /etc/receipt-ocr-poc/config.json from config.json.example.
3. Put drive.json, vision.json and firestore.json in secrets/ with mode 0600.
4. Run the dry-run command from docs/OCI_POC_SETUP.md.
5. Enable receipt-ocr-poc.timer only after the dry-run succeeds.
6. Set poc.llm.enabled=true, run Codex device login as receipt-ocr-codex, and verify auth-mode is ChatGPT.
7. Enable receipt-ocr-llm.timer and receipt-ocr-llm-health.timer after the health check succeeds.
EOF
chown "${APP_USER}:${APP_GROUP}" "${STATE_DIR}/NEXT_STEPS.txt"
chmod 0640 "${STATE_DIR}/NEXT_STEPS.txt"
touch "${COMPLETE_MARKER}"
chown "${APP_USER}:${APP_GROUP}" "${COMPLETE_MARKER}"
chmod 0640 "${COMPLETE_MARKER}"

echo "[$(date --iso-8601=seconds)] receipt-ocr PoC bootstrap completed"
