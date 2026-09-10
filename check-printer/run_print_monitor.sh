#!/bin/bash
# Launch Print Monitor's browser dashboard at login or by double-clicking.
# Keep this file in the same folder as print_monitor_web.py and venv/.

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
APP_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"

cd "$APP_DIR"

if [ ! -f "venv/bin/activate" ]; then
  osascript -e 'display dialog "Print Monitor cannot start: venv/bin/activate was not found." buttons {"OK"} default button "OK" with icon stop'
  exit 1
fi

source venv/bin/activate
exec python3 "$APP_DIR/print_monitor_web.py"
