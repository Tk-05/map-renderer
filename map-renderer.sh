#!/usr/bin/env sh
# Starts the map-renderer tool (tools/map_renderer). All arguments are passed through.
# Without arguments the interactive assistant starts.
set -e

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
CHECK='import sys; sys.exit(sys.version_info < (3, 10))'

# python3 first (Linux/macOS), then python and the Windows launcher (Git Bash).
for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c "$CHECK" >/dev/null 2>&1; then
        exec "$py" "$ROOT/tools/map_renderer" "$@"
    fi
done
if command -v py >/dev/null 2>&1 && py -3 -c "$CHECK" >/dev/null 2>&1; then
    exec py -3 "$ROOT/tools/map_renderer" "$@"
fi

echo "Python 3.10 or newer was not found. Install it, e.g.: sudo apt install python3" >&2
exit 127
