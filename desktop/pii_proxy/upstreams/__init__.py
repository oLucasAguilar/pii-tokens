"""The upstream MCP servers this proxy knows, one module each.

A tool profile is chosen per server (the extension's Preset field). Formats are all read, whatever the
server: a layout recognized anywhere gets masked.
"""

from . import metabase
from .base import Format, Profile

GENERIC = Profile()

PROFILES = {"": GENERIC, "metabase": metabase.PROFILE}
FORMATS = (*metabase.FORMATS,)
