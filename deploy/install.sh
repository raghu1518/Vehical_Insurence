#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-multilingual-bot}"
DISPLAY_NAME="${DISPLAY_NAME:-Multilingual Multi-Agent Bot}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9019}"
WORKING_DIR="${WORKING_DIR:-}"
PYTHON_BIN="${PYTHON:-}"
RUN_USER="${RUN_USER:-}"
ENV_FILE="${ENV_FILE:-}"

if [[ -z "$WORKING_DIR" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  WORKING_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

if [[ ! -d "$WORKING_DIR" ]]; then
  echo "Project root not found: $WORKING_DIR" >&2
  exit 1
fi

if [[ -z "$RUN_USER" ]]; then
  RUN_USER="$(id -un)"
  if [[ -n "${SUDO_USER:-}" && "$RUN_USER" == "root" ]]; then
    RUN_USER="$SUDO_USER"
  fi
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run with sudo/root to install systemd service." >&2
  exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$WORKING_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$WORKING_DIR/.venv/bin/python"
  else
    if command -v python3 >/dev/null 2>&1; then
      SYS_PYTHON="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
      SYS_PYTHON="$(command -v python)"
    else
      echo "Python not found. Install python3." >&2
      exit 1
    fi
    echo "Creating venv..."
    "$SYS_PYTHON" -m venv "$WORKING_DIR/.venv"
    PYTHON_BIN="$WORKING_DIR/.venv/bin/python"
  fi

  echo "Installing requirements..."
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$WORKING_DIR/requirements.txt"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

ENV_LINE=""
if [[ -n "$ENV_FILE" ]]; then
  if [[ "$ENV_FILE" != /* ]]; then
    echo "ENV_FILE must be an absolute path." >&2
    exit 1
  fi
  ENV_LINE="EnvironmentFile=$ENV_FILE"
fi

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=$DISPLAY_NAME
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$WORKING_DIR
$ENV_LINE
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_BIN -m uvicorn app:app --host $HOST --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Service installed and running: $SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager || true
