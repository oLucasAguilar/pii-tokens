#!/usr/bin/env python3
"""Zip the Claude Desktop extension: manifest, pyproject, the proxy package and the masking library.

Usage: python3 desktop/build.py [output path, default build/pii-tokens.mcpb]
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"


def entries():
    yield DESKTOP / "manifest.json", "manifest.json"
    yield DESKTOP / "pyproject.toml", "pyproject.toml"
    yield DESKTOP / "icon.png", "icon.png"
    yield ROOT / "plugin" / "scripts" / "pii.py", "pii.py"
    for source in sorted((DESKTOP / "pii_proxy").rglob("*.py")):
        yield source, source.relative_to(DESKTOP).as_posix()


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "pii-tokens.mcpb"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for source, name in entries():
            bundle.write(source, name)
    print(output)


if __name__ == "__main__":
    main()
