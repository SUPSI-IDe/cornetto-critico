#!/bin/bash
# Opens Print Monitor as a separate Chrome app-style window (no address bar,
# tabs, or normal browser window controls). It does NOT start the monitor;
# the LaunchAgent starts the background Python process.
#
# This script is safe to add as a macOS Login Item if you want the dashboard
# window to appear immediately after login.

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
APP_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"

PORT="$(grep -E '^PRINT_MONITOR_PORT=' "$APP_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
PORT="${PORT:-8765}"
URL="http://127.0.0.1:${PORT}"
PROFILE_DIR="$APP_DIR/.print-monitor-browser-profile"

# Google Chrome is preferred because --app opens a dedicated, minimal app
# window. Chromium is tried too. The browser profile is isolated, so it won't
# modify or use your normal personal Chrome session.
if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --app="$URL" \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check
elif [ -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ]; then
  exec "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    --app="$URL" \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run
else
  # Fallback: still opens the dashboard, but in the default browser.
  /usr/bin/open "$URL"
fi

