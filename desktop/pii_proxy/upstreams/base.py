"""What changes from one upstream MCP server to another."""

import dataclasses
import re
from typing import Callable


@dataclasses.dataclass(frozen=True)
class Profile:
    """Tools to expose or hide, on top of the generic rule: only tools marked read-only."""

    allow: frozenset = frozenset()
    block: frozenset = frozenset()


@dataclasses.dataclass(frozen=True)
class Format:
    """A layout an upstream uses for personal data, which the masking must read to find names.

    wrapper: text around a JSON payload, the payload in group 2.
    table: the value with its cells masked by column, or None when the value is not this table.
    hint: what this format's data looks like; seen outside the format, the result is withheld.
    """

    wrapper: re.Pattern | None = None
    table: Callable | None = None
    hint: re.Pattern | None = None
