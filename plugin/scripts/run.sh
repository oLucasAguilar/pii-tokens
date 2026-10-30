#!/bin/sh
# Prefer the plugin venv; fall back to the system Python, where tokens become irreversible but masking still runs.
here=$(dirname "$0")
python=$("$here/find_python.sh" "${CLAUDE_PLUGIN_DATA:-/nonexistent}/venv")
# CLAUDE_PLUGIN_DATA is only set for hooks; the pii-* commands look where Claude Code keeps plugin data.
if [ -z "$python" ]; then
  for venv in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/data/pii-tokens-*/venv; do
    python=$("$here/find_python.sh" "$venv") && break
  done
fi
[ -n "$python" ] || python=$("$here/find_python.sh") || python=python3
script="$1"
shift
exec "$python" "$here/$script" "$@"
