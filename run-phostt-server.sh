#!/usr/bin/env sh
# Install dependencies (first run) and start the server.
set -e
cd "$(dirname "$0")"

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

# Settings (PORT, NUM_THREADS, ...) come from .env if present; see .env.example.
# Variables already set in the environment take precedence over .env.
if [ -f .env ]; then
    set -- --env-file .env
fi

echo "Starting server..."
exec uv run --frozen "$@" src/main.py
