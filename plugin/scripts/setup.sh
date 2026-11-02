#!/bin/sh
# Install the vault dependencies into the plugin data directory, once per requirements change.
root="${CLAUDE_PLUGIN_ROOT:?}"
data="${CLAUDE_PLUGIN_DATA:?}"
mkdir -p "$data"
if [ "$OS" = Windows_NT ]; then
  # Git Bash copies instead of linking, and a copied pii-* cannot find ../scripts. Write launchers for this
  # version instead: one for Git Bash, and a .cmd so PowerShell and cmd can run them too. Paths are relative
  # to the launcher, so the user folder, whose accents cmd.exe may misread, is never written into them.
  plugins=${data%/data/*}
  case $root in
    "$plugins"/*) sh_root="\$(dirname \"\$0\")/../../..${root#"$plugins"}"
                  cmd_root="%~dp0..\\..\\..$(printf %s "${root#"$plugins"}" | tr / '\\')" ;;
    *) sh_root=$root; cmd_root=$(cygpath -w "$root") ;;
  esac
  rm -rf "$data/bin" && mkdir "$data/bin"
  for cmd in "$root"/bin/*; do
    name=$(basename "$cmd")
    printf '#!/bin/sh\nexec "%s/bin/%s" "$@"\n' "$sh_root" "$name" > "$data/bin/$name"
    # Without the plugin venv, fall back to the system Python, like run.sh.
    printf '@setlocal\r\n@set "py=%%~dp0..\\venv\\Scripts\\python.exe"\r\n@if not exist "%%py%%" set "py=python"\r\n@"%%py%%" "%s\\scripts\\cli.py" %s %%*\r\n' "$cmd_root" "$name" > "$data/bin/$name.cmd"
  done
else
  ln -sfn "$root/bin" "$data/bin"
fi
# Revealed copies are plain text; without this they outlive their 24h until the next pii-reveal.
find "$HOME/.cache/pii-tokens/reveal" -type f -mmin +1440 -delete 2>/dev/null
cmp -s "$root/requirements.txt" "$data/requirements.txt" && exit 0
python=$("$root/scripts/find_python.sh")
pip_install="install --quiet --disable-pip-version-check --require-hashes"
# A venv without its own pip is ready in 0.1 s instead of 10 (measured on Windows), and the system pip fills it;
# where the system Python has no pip, the venv brings its own, as before.
fast() { "$python" -m venv --without-pip "$data/venv" && "$python" -m pip --python "$("$root/scripts/find_python.sh" "$data/venv")" $pip_install -r "$root/requirements.txt"; }
usual() { "$python" -m venv "$data/venv" && "$("$root/scripts/find_python.sh" "$data/venv")" -m pip $pip_install -r "$root/requirements.txt"; }
if [ -n "$python" ] && { fast || usual; } >/dev/null 2>&1; then
  cp "$root/requirements.txt" "$data/requirements.txt"
else
  echo "[pii-tokens] could not install keyring/cryptography into $data/venv; masking still runs, but tokens cannot be reversed. Needs Python 3.10+ with venv." >&2
fi
exit 0
