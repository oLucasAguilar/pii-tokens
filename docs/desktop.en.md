# Claude Desktop

In Claude Desktop chat, plugin hooks do not run. So the plugin does not protect what an MCP server returns there.

For that case there is a Desktop extension: a local MCP server between Claude and the real server, which masks the result before Claude reads it.

```
Claude Desktop ──> pii-tokens (on your computer) ──> MCP server
                   masks what comes back
```

- The masking is the plugin's, with the same vault and the same tokens.
- Works with a remote (HTTP) MCP server, with or without OAuth.
- **Use it in Claude mode** (the chat, the icon left of `</>`). In Code mode the extension does not reach the session; there, the plugin protects.
- Tested in Claude Desktop 4.29 for Windows, with [Metabase](#metabase).

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
| Preset | Ready-made rules for a known server, such as `metabase`. Empty: the generic rules |
| Extra headers | JSON sent on every request, for an auth proxy in front of the server |
| Also allow / Block these tools | Comma-separated tool names to allow or block |
| Unmask in queries | Kinds (`CPF`, `CNPJ`, `EMAIL`, `PHONE`) whose token becomes the real value in what Claude sends |

## Which tools Claude sees

- **No preset:** only those the server marks read-only (`readOnlyHint`).
- **With a preset:** that server's rules, below.
- **Block wins over allow.** A hidden tool is also refused when Claude calls it by name.
- The server's resources and prompts do not pass.

## What is masked

- **CPF, CNPJ, email and phone:** anywhere in the result, by format.
- **Names:** by column, in the table formats the extension knows (today, Metabase's), from any server.
- **A name in plain JSON** (outside a known table) passes.

## Sign-in (OAuth)

- On first use your browser opens.
- After that, the sign-in lasts across restarts.
- The token is encrypted on disk, with the key in the system keyring.

## Unmasking in queries

With `Unmask in queries` empty (the default), a token Claude writes in a query reaches the server as text. To follow a record, Claude uses its ID.

Turned on, Claude filters by the real value without reading it, but a crafted query brings part of it back.

- Names are never unmasked.

## Limits of the Desktop extension

Those in [limits.en.md](limits.en.md) apply too. Besides them:

- **A renamed column passes.** Names are found by column, so `SELECT name AS title` returns the name unmasked.
- **What you type or attach in the chat is not masked.** Without a hook, it goes straight to the model. For that, use Code mode with the plugin.
- **A result in an unknown shape is withheld**, not passed on: Claude gets a notice instead.
- **A block that is not text** (image, embedded resource) is withheld too.

## Metabase

Preset `metabase`. Tested with Metabase 0.64 and 0.65.

- Allows `execute_sql`, which reads but is not marked (so Desktop lists it under "Write/delete").
- Hides `visualize_query`, `render_drill_through` and `get_parameter_values`, whose data does not pass through the masking.
- The sign-in may show a second screen on the first SQL query.
- Measured: `SELECT name AS title` passed 5 of 5. To close it, block `execute_sql` and keep `execute_query`.
- Measured: with `Unmask in queries` on, `SUBSTRING('EMAIL#...', 1, n)` returned the start of the email.

Another server gets its rules in a module under `desktop/pii_proxy/upstreams/`.
