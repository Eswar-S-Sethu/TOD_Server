#!/usr/bin/env bash
# Run this script on the NUC as root (or with sudo) after cloning the repo.
# Usage: sudo bash deploy/install.sh <your-linux-username>
#
# What it does:
#   1. Copies the app to /opt/tod-server
#   2. Installs Python dependencies into the venv
#   3. Installs and enables the tod-server systemd unit
#   4. Installs and enables the cloudflared systemd unit (cloudflared must
#      already be authenticated and configured — see ENDPOINTS.md / README)

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install.sh <username>"
  exit 1
fi

TARGET_USER="${1:-}"
if [[ -z "$TARGET_USER" ]]; then
  echo "Usage: sudo bash deploy/install.sh <your-linux-username>"
  exit 1
fi

DEPLOY_DIR="/opt/tod-server"

echo "==> Copying app to $DEPLOY_DIR"
rsync -a --exclude='.git' --exclude='Trolleys' "$(dirname "$(realpath "$0")")/../" "$DEPLOY_DIR/"
chown -R "$TARGET_USER:$TARGET_USER" "$DEPLOY_DIR"

echo "==> Setting up Python venv"
sudo -u "$TARGET_USER" python3 -m venv "$DEPLOY_DIR/.venv"
sudo -u "$TARGET_USER" "$DEPLOY_DIR/.venv/bin/pip" install --quiet flask pillow piexif requests

echo "==> Installing tod-server systemd unit"
# Patch the placeholder username into the service file
sed "s/TOD_USER/$TARGET_USER/g" "$DEPLOY_DIR/deploy/tod-server.service" \
  > /etc/systemd/system/tod-server.service

systemctl daemon-reload
systemctl enable --now tod-server
echo "    tod-server status: $(systemctl is-active tod-server)"

echo "==> Installing cloudflared systemd unit"
echo "    (assumes 'cloudflared tunnel login' and config.yml are already done)"
cloudflared service install
systemctl enable --now cloudflared
echo "    cloudflared status: $(systemctl is-active cloudflared)"

echo ""
echo "Done. Useful commands:"
echo "  journalctl -u tod-server -f      # Flask logs"
echo "  journalctl -u cloudflared -f     # Tunnel logs"
echo "  systemctl restart tod-server     # Restart Flask"
echo "  systemctl restart cloudflared    # Restart tunnel"
