"""Masks a tool result before Claude sees it.

A name is found by its column, in the table formats the upstreams use; any other string is masked by
its format (CPF, CNPJ, email, phone).
"""

import functools
import json
import re
import sys
import unicodedata
from pathlib import Path

from . import upstreams

try:
    import pii
except ImportError:
    # The extension ships pii.py beside this package (desktop/build.py), so this only runs from the
    # repository. The plugin is a folder of scripts, not an installable package, so a path is all
    # there is to find it by.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin" / "scripts"))
    import pii


def vault() -> "pii.Vault":
    return pii.Vault()


class Withheld(ValueError):
    """The result holds data in a shape this proxy does not know, so it cannot vouch for the masking."""


class Masker:
    def __init__(self, vault: "pii.Vault", unmask_kinds=frozenset(), formats=upstreams.FORMATS):
        self.vault = vault
        self.unmask_kinds = unmask_kinds
        self._wrappers = [f.wrapper for f in formats if f.wrapper]
        self._tables = [f.table for f in formats if f.table]
        hints = [f.hint.pattern for f in formats if f.hint]
        self._hint = re.compile("|".join(hints)) if hints else None

    def text(self, text: str) -> str:
        for wrapper in self._wrappers:
            parts, last = [], 0
            for match in wrapper.finditer(text):
                parts.append(self._loose(text[last : match.start()]))
                parts.append(text[match.start() : match.start(2)])
                parts.append(self._json(match.group(2)))
                parts.append(text[match.end(2) : match.end()])
                last = match.end()
            if parts:
                return "".join(parts) + self._loose(text[last:])
        if text.lstrip()[:1] in ("{", "["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return self._loose(text)
            return _dump(self.value(value))
        return self._loose(text)

    def value(self, value):
        """Decoded JSON: tables by column, strings as text blocks of their own."""
        if isinstance(value, dict):
            for table in self._tables:
                masked = table(value, self._cell)
                if masked is not None:
                    return masked
            return {k: self.value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(v) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def unmask(self, arguments):
        """Tokens of the unmask kinds turned back into real values, before the call goes upstream.

        Only kinds that the result masking finds again by format belong here: a NAME token unmasked in a
        `SELECT 'NAME#...' AS title` would come back as a plain name under a column that does not say so.
        """
        if not self.unmask_kinds:
            return arguments
        if isinstance(arguments, dict):
            return {k: self.unmask(v) for k, v in arguments.items()}
        if isinstance(arguments, list):
            return [self.unmask(v) for v in arguments]
        if isinstance(arguments, str):
            return pii.TOKEN_RE.sub(lambda m: self._real_value(m.group(0)), arguments)
        return arguments

    def _loose(self, text):
        if self._hint and self._hint.search(text):
            raise Withheld("data outside a recognized shape")
        return pii.mask_text(text, self.vault)

    def _json(self, text):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as e:
            raise Withheld("data that is not valid JSON") from e
        return _dump(self.value(value))

    def _cell(self, column, cell):
        if cell is None or isinstance(cell, bool):
            return cell
        kind = _column_kind(column)
        if kind:
            return pii.mask_cell(kind, str(cell), self.vault) if isinstance(cell, str) or kind == "DOC" else cell
        return self.value(cell)

    def _real_value(self, token):
        if token.split("#", 1)[0] not in self.unmask_kinds:
            return token
        return self.vault.value_for(token) or token


@functools.lru_cache(maxsize=512)
def _column_kind(column: str):
    return pii.column_kind(column)


def _dump(value):
    return _escape_invisible(json.dumps(value, ensure_ascii=False))


def _escape_invisible(text):
    """Keep zero-width and other format characters escaped, as upstreams send them."""
    return "".join(f"\\u{ord(ch):04x}" if unicodedata.category(ch) == "Cf" else ch for ch in text)
