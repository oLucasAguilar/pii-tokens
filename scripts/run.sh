#!/bin/sh
# Prefer the plugin venv; fall back to system python3, where tokens become irreversible but masking still runs.
here=$(dirname "$0")
python="${CLAUDE_PLUGIN_DATA:-/nonexistent}/venv/bin/python"
# CLAUDE_PLUGIN_DATA is only set for hooks; the pii-* commands look where Claude Code keeps plugin data.
if [ ! -x "$python" ]; then
  for candidate in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/data/pii-tokens-*/venv/bin/python; do
    [ -x "$candidate" ] && python="$candidate" && break
  done
fi
[ -x "$python" ] || python=python3
script="$1"
shift
exec "$python" "$here/$script" "$@"
