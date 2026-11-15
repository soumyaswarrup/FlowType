#!/usr/bin/env bash
# Start (or restart) FlowType on macOS / Linux
cd "$(dirname "$0")"
pkill -f "$(pwd)/flowtype.py" 2>/dev/null; sleep 0.5
nohup .venv/bin/python "$(pwd)/flowtype.py" >/dev/null 2>&1 &
echo "FlowType started."
