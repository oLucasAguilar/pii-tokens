"""Metabase: which of its tools are safe, and how its query results carry names."""

import re

from .base import Format, Profile

PROFILE = Profile(
    # Runs read-only SQL but is not marked read-only.
    allow=frozenset({"execute_sql"}),
    # Their data reaches Claude without passing through here (a chart iframe) or is raw column values with no column to mask by.
    block=frozenset({"visualize_query", "render_drill_through", "get_parameter_values"}),
)

# v0.65+ wraps data as <data boundary="uuid">\n{json}\n</data boundary="uuid">.
ENVELOPE = Format(
    wrapper=re.compile(r'<data boundary="([^"]+)">\n(.*?)\n</data boundary="\1">', re.S),
    hint=re.compile(r"<data boundary="),
)


def _query_result(value, mask_cell):
    if not (isinstance(value, dict) and isinstance(value.get("cols"), list) and isinstance(value.get("rows"), list)):
        return None
    columns = [str(col.get("name", "")) for col in value["cols"]]
    rows = [[mask_cell(columns[i] if i < len(columns) else "", cell) for i, cell in enumerate(row)] for row in value["rows"]]
    return {**value, "rows": rows}


# Rows come apart from their columns, so a name is found by its column, the way the plugin masks a psql table.
QUERY_RESULT = Format(table=_query_result, hint=re.compile(r'"(?:rows|cols)"\s*:'))

FORMATS = (ENVELOPE, QUERY_RESULT)
