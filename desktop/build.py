#!/usr/bin/env python3
"""Zip the Claude Desktop extension: manifest, pyproject, the proxy package and the masking library.

Usage: python3 desktop/build.py [output path, default build/pii-tokens.mcpb]
       python3 desktop/build.py --check <downloaded .mcpb>   compare a bundle with this folder's code
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
TEXT = (".py", ".json", ".toml")


def entries():
    yield DESKTOP / "manifest.json", "manifest.json"
    yield DESKTOP / "pyproject.toml", "pyproject.toml"
    yield DESKTOP / "icon.png", "icon.png"
    yield ROOT / "plugin" / "scripts" / "pii.py", "pii.py"
    for source in sorted((DESKTOP / "pii_proxy").rglob("*.py")):
        yield source, source.relative_to(DESKTOP).as_posix()


def comparable(name, data):
    # A Windows clone has CRLF, and the zip bytes depend on the zlib build: only the content counts.
    return data.replace(b"\r\n", b"\n") if name.endswith(TEXT) else data


def check(path):
    expected = {name: comparable(name, source.read_bytes()) for source, name in entries()}
    with zipfile.ZipFile(path) as bundle:
        found = {name: comparable(name, bundle.read(name)) for name in bundle.namelist()}
    differ = sorted(name for name in expected.keys() | found.keys() if expected.get(name) != found.get(name))
    for name in differ:
        where = " (only in the bundle)" if name not in expected else " (missing from the bundle)" if name not in found else ""
        print(f"differs: {name}{where}")
    print(f"{len(differ)} file(s) differ" if differ else "same code as this folder")
    return 1 if differ else 0


def main():
    if sys.argv[1:2] == ["--check"]:
        sys.exit(check(Path(sys.argv[2])))
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "pii-tokens.mcpb"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for source, name in entries():
            bundle.write(source, name)
    print(output)


if __name__ == "__main__":
    main()
