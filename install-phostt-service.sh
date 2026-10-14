#!/usr/bin/env sh
# Install and start phostt-server as a systemd service.
set -e

sudo tee /etc/systemd/system/phostt-stt-server.service > /dev/null <<'EOF'
[Unit]
Description=phostt STT Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=atoma
WorkingDirectory=/home/atoma/Atoma/phostt-server
EnvironmentFile=-/home/atoma/Atoma/phostt-server/.env
ExecStart=/home/atoma/.local/bin/uv run --frozen src/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now phostt-stt-server
echo "Follow the logs with: journalctl -u phostt-stt-server -f"
