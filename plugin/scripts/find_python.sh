#!/bin/sh
# Prints the Python 3.10+ to run: the one in the venv given as argument, or else the system's.
# Windows installs Python as "python", and its venv keeps the executables in Scripts.
if [ -n "$1" ]; then
  for candidate in "$1/bin/python" "$1/Scripts/python.exe"; do
    [ -x "$candidate" ] && echo "$candidate" && exit 0
  done
  exit 1
fi
for candidate in python3 python; do
  "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && echo "$candidate" && exit 0
done
exit 1
