#!/usr/bin/env sh
# Install dependencies (first run) and start the server.
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8123}"

if ! command -v uv >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/uv" ]; then
        PATH="$HOME/.local/bin:$PATH"
    else
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        PATH="$HOME/.local/bin:$PATH"
    fi
    export PATH
fi

echo "Installing dependencies..."
uv sync --frozen

echo "Starting server on port $PORT..."
exec uv run --frozen src/main.py --port "$PORT"
