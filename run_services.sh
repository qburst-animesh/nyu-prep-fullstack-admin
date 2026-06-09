#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Start backend (uvicorn)
echo "Starting backend..."
cd "$SCRIPT_DIR/backend-admin-panel"
# Start backend in background, write logs and PID
uvicorn app_fastapi.main:app --reload --host 0.0.0.0 --port 8000 > "$SCRIPT_DIR/backend.log" 2>&1 &
echo $! > "$SCRIPT_DIR/backend.pid"
cd "$SCRIPT_DIR"

# Start frontend (vite)
echo "Starting frontend..."
cd "$SCRIPT_DIR/frontend-admin-panel"
npm run dev > "$SCRIPT_DIR/frontend.log" 2>&1 &
echo $! > "$SCRIPT_DIR/frontend.pid"
cd "$SCRIPT_DIR"

echo "Services started. Backend PID: $(cat "$SCRIPT_DIR/backend.pid"), Frontend PID: $(cat "$SCRIPT_DIR/frontend.pid")."
echo "Logs: $SCRIPT_DIR/backend.log, $SCRIPT_DIR/frontend.log"

echo "To stop: kill $(cat "$SCRIPT_DIR/backend.pid") $(cat "$SCRIPT_DIR/frontend.pid")"
