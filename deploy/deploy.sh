#!/usr/bin/env bash
# Mac side: bash deploy/deploy.sh <vm-name> <zone>. Ships committed HEAD only.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 <vm-name> <zone>" >&2; exit 2; }
cd "$(git rev-parse --show-toplevel)"
git diff --quiet && git diff --cached --quiet || { echo "deploy: working tree is dirty, commit first" >&2; exit 1; }
git archive HEAD deploy gtm pyproject.toml uv.lock | gcloud compute ssh "$1" --zone "$2" -- '
  set -e
  sudo tar -x -C /opt/gtm --no-same-owner
  sudo chmod +x /opt/gtm/deploy/*.sh
  sudo -u gtm uv sync --frozen --no-dev --project /opt/gtm
  sudo cp /opt/gtm/deploy/gtm-worker.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable gtm-worker
  sudo systemctl restart gtm-worker
  sleep 3
  systemctl is-active gtm-worker'
