#!/usr/bin/env bash
# Run once on the VM as root: sudo bash bootstrap.sh. Idempotent. Does not start the worker.
set -euo pipefail
id gtm >/dev/null 2>&1 || useradd --system --home-dir /opt/gtm --shell /usr/sbin/nologin gtm
# /opt/gtm stays root-owned: root runs deploy/fetch_secrets.sh from it, so gtm must not be able to replace it.
mkdir -p /opt/gtm/.venv /opt/gtm/.cache /opt/gtm/.python /opt/gtm/.secrets && chown gtm /opt/gtm/.venv /opt/gtm/.cache /opt/gtm/.python /opt/gtm/.secrets
if [ ! -f /swapfile ]; then  # e2-micro has 1 GB RAM
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon --show=NAME --noheadings | grep -q /swapfile || swapon /swapfile
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
# fetch_secrets.sh names the Gmail token file from GTM_MAILBOX
mkdir -p /etc/systemd/system/gtm-worker.service.d
printf '[Service]\nEnvironment=GTM_MAILBOX=soban@kodoai.xyz\n' > /etc/systemd/system/gtm-worker.service.d/mailbox.conf
systemctl daemon-reload
echo "bootstrap done; deploy.sh installs and enables the unit"
