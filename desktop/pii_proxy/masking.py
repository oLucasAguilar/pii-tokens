"""Masks a tool result before Claude sees it.

Metabase returns query rows apart from their columns, so a name is found by its column, the way the
plugin masks a psql table; any other string is masked by its format (CPF, CNPJ, email, phone).
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

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


# Metabase v0.65+ wraps data as <data boundary="uuid">\n{json}\n</data boundary="uuid">.
ENVELOPE = re.compile(r'<data boundary="([^"]+)">\n(.*?)\n</data boundary="\1">', re.S)
# Data that none of the shapes above explained: refused rather than passed on with names in it.
DATA_HINT = re.compile(r'"(?:rows|cols)"\s*:|<data boundary=')


class Unrecognized(ValueError):
    """The result holds data in a shape this proxy does not know, so it cannot vouch for the masking."""


def mask_text_block(text: str, vault: "pii.Vault") -> str:
    parts, last = [], 0
    for envelope in ENVELOPE.finditer(text):
        parts.append(_mask_loose_text(text[last:envelope.start()], vault))
        parts.append(text[envelope.start():envelope.start(2)])
        parts.append(_mask_json_text(envelope.group(2), vault))
        parts.append(text[envelope.end(2):envelope.end()])
        last = envelope.end()
    if parts:
        return "".join(parts) + _mask_loose_text(text[last:], vault)
    if text.lstrip()[:1] in ("{", "["):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return _mask_loose_text(text, vault)
        return _dump(mask_value(value, vault))
    return _mask_loose_text(text, vault)


def _mask_loose_text(text, vault):
    if DATA_HINT.search(text):
        raise Unrecognized("data outside a recognized shape")
    return pii.mask_text(text, vault)


def _mask_json_text(text, vault):
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise Unrecognized("data that is not valid JSON") from e
    return _dump(mask_value(value, vault))


def _dump(value):
    return _escape_invisible(json.dumps(value, ensure_ascii=False))


def _escape_invisible(text):
    """Keep zero-width and other format characters escaped, as Metabase sends them."""
    return "".join(f"\\u{ord(ch):04x}" if unicodedata.category(ch) == "Cf" else ch for ch in text)


def mask_value(value, vault: "pii.Vault"):
    """Mask decoded JSON: query results by column, strings as text blocks of their own."""
    if isinstance(value, dict):
        if isinstance(value.get("cols"), list) and isinstance(value.get("rows"), list):
            return _mask_query(value, vault)
        return {k: mask_value(v, vault) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(v, vault) for v in value]
    if isinstance(value, str):
        return mask_text_block(value, vault)
    return value


def _mask_query(result, vault):
    kinds = [pii.column_kind(str(col.get("name", ""))) for col in result["cols"]]
    rows = [[_mask_cell(kinds[i] if i < len(kinds) else None, cell, vault) for i, cell in enumerate(row)] for row in result["rows"]]
    return {**result, "rows": rows}


def _mask_cell(kind, cell, vault):
    if cell is None or isinstance(cell, bool):
        return cell
    if kind:
        return pii.mask_cell(kind, str(cell), vault) if isinstance(cell, str) or kind == "DOC" else cell
    return mask_value(cell, vault)


def unmask_arguments(arguments, kinds: set[str], vault: "pii.Vault"):
    """Turn tokens of the given kinds back into real values before the call goes upstream.

    Only kinds that the result masking finds again by format belong here: a NAME token unmasked in a
    `SELECT 'NAME#...' AS title` would come back as a plain name under a column that does not say so.
    """
    if not kinds:
        return arguments
    if isinstance(arguments, dict):
        return {k: unmask_arguments(v, kinds, vault) for k, v in arguments.items()}
    if isinstance(arguments, list):
        return [unmask_arguments(v, kinds, vault) for v in arguments]
    if isinstance(arguments, str):
        return pii.TOKEN_RE.sub(lambda m: _real_value(m.group(0), kinds, vault), arguments)
    return arguments


def _real_value(token, kinds, vault):
    if token.split("#", 1)[0] not in kinds:
        return token
    return vault.value_for(token) or token
