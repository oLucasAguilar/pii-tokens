# Claude Desktop

In Claude Desktop chat, plugin hooks do not run. So the plugin does not protect what an MCP server returns there.

For that case there is a Desktop extension: a local MCP server between Claude and the real server, which masks the result before Claude reads it.

```
Claude Desktop ──> pii-tokens (on your computer) ──> MCP server (Metabase, for example)
                   masks what comes back
```

- The masking is the plugin's, with the same vault and the same tokens.
- Works with a remote (HTTP) MCP server, with or without OAuth.
- **Not yet tested in Claude Desktop.** Tested against a real Metabase, running the package the way Desktop runs it, on Linux.

## Install

1. In the repository, run `make desktop-bundle`. It writes `build/pii-tokens.mcpb`.
2. Open the file in Claude Desktop (macOS or Windows). Desktop installs Python and the dependencies itself.
3. Fill in the fields and turn the extension on.

Do not also add the same server as a direct connector: that way results reach Claude unmasked.

## Fields

| Field | What for |
|---|---|
| MCP server URL | The server Claude reaches through the extension |
| Authentication | `oauth` opens the server's sign-in page in your browser on first use. Empty: no sign-in |
| Preset | Tool rules for a known server. Today there is `metabase` |
| Extra headers | JSON sent on every request, sign-in included. For an auth proxy in front of the server, such as a Cloudflare Access service token |
| Also allow / Block these tools | Comma-separated tool names to allow or block |
| Unmask in queries | Kinds (`CPF`, `CNPJ`, `EMAIL`, `PHONE`) whose token becomes the real value in what Claude sends |

## Which tools Claude sees

- **No preset:** only those the server marks read-only (`readOnlyHint`).
- **`metabase` preset:**
	- allows `execute_sql`, which reads but is not marked;
	- hides `visualize_query` and `render_drill_through`, whose chart fetches rows straight from Metabase, outside the extension;
	- hides `get_parameter_values`, which returns column values with no column to mask by.
- **Block wins over allow.** A hidden tool is also refused when Claude calls it by name.
- The server's resources and prompts do not pass.

## Sign-in (OAuth)

- On first use your browser opens. Metabase may show a second screen on the first SQL query, because the SQL scope is asked for when it is needed.
- After that, the sign-in lasts across restarts.
- The token is encrypted on disk, with the key in the system keyring. The keyring alone would not do: Windows refuses values over 2560 bytes.

## Unmasking in queries

With `Unmask in queries` empty (the default), a token Claude writes in a query reaches the server as text. To follow a record, Claude uses its ID.

Turned on, Claude filters by the real value without reading it, but a crafted query brings part of it back.

- Measured on Metabase: `SUBSTRING('EMAIL#...', 1, n)` returned the start of the email.
- Names are never unmasked. They are not recognized by format on the way back, so they would return unmasked.

## Limits of the Desktop extension

Those in [limits.en.md](limits.en.md) apply too. Besides them:

- **A renamed column in SQL passes.** `SELECT name AS title` returns the name unmasked, because columns are recognized by name. On Metabase, measured: 5 of 5. To close it, block `execute_sql` and keep `execute_query`.
- **What you type in the chat is not masked.** Without a hook, the prompt goes straight to the model.
- **A result in an unknown shape is withheld**, not passed on: Claude gets a notice instead.
- **A block that is not text** (image, embedded resource) is withheld too.
