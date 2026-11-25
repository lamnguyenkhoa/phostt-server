#!/usr/bin/env sh
# Install and start phostt-server as a systemd service.
# Run as the account that installed uv (not with sudo); it asks for sudo when needed.
# The service runs as that account, from the folder this script is in.
set -e

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, not root/sudo. It calls sudo itself." >&2
    exit 1
fi

SERVICE_USER="$(id -un)"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

UV_BIN="$(command -v uv || true)"
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
fi
if [ -z "$UV_BIN" ]; then
    echo "uv not found. Run ./run-phostt-server.sh once first to install it." >&2
    exit 1
fi

echo "User:    $SERVICE_USER"
echo "Folder:  $APP_DIR"
echo "uv:      $UV_BIN"

sudo tee /etc/systemd/system/phostt-stt-server.service > /dev/null <<EOF
[Unit]
Description=phostt STT Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=-$APP_DIR/.env
ExecStart="$UV_BIN" run --frozen src/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now phostt-stt-server
echo "Follow the logs with: journalctl -u phostt-stt-server -f"
