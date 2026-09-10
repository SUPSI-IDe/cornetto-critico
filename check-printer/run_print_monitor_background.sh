#!/bin/bash
# Starts the Print Monitor server without a Terminal window.
# This script is intended for launchd / a macOS LaunchAgent.
# Keep it alongside print_monitor_web.py, .env, and venv/.

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
APP_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"

cd "$APP_DIR"

if [ ! -f "venv/bin/python3" ]; then
  echo "ERROR: venv/bin/python3 was not found in $APP_DIR" >&2
  exit 1
fi

# `exec` lets launchd supervise the Python monitor directly.
exec "$APP_DIR/venv/bin/python3" "$APP_DIR/print_monitor_web.py"

