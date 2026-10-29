#!/bin/sh
# Install the vault dependencies into the plugin data directory, once per requirements change.
root="${CLAUDE_PLUGIN_ROOT:?}"
data="${CLAUDE_PLUGIN_DATA:?}"
mkdir -p "$data" && ln -sfn "$root/bin" "$data/bin"
# Revealed copies are plain text; without this they outlive their 24h until the next pii-reveal.
find "$HOME/.cache/pii-tokens/reveal" -type f -mmin +1440 -delete 2>/dev/null
cmp -s "$root/requirements.txt" "$data/requirements.txt" && exit 0
if python3 -m venv "$data/venv" >/dev/null 2>&1 \
  && "$data/venv/bin/pip" install --quiet --require-hashes -r "$root/requirements.txt" >/dev/null 2>&1; then
  cp "$root/requirements.txt" "$data/requirements.txt"
else
  echo "[pii-tokens] could not install keyring/cryptography into $data/venv; masking still runs, but tokens cannot be reversed. Needs Python 3.10+ with venv." >&2
fi
exit 0
