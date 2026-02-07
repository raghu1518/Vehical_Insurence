#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-multilingual-bot}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run with sudo/root to uninstall systemd service." >&2
  exit 1
fi

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then
  systemctl stop "$SERVICE_NAME" || true
  systemctl disable "$SERVICE_NAME" || true
fi

if [[ -f "$UNIT_FILE" ]]; then
  rm -f "$UNIT_FILE"
  systemctl daemon-reload
  systemctl reset-failed "$SERVICE_NAME" || true
fi

echo "Service removed: $SERVICE_NAME"
