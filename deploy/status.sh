#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-multilingual-bot}"

systemctl status "$SERVICE_NAME" --no-pager || true
echo
journalctl -u "$SERVICE_NAME" --no-pager -n 50 || true
