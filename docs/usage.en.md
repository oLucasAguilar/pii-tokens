# Using pii-tokens

Setup details and notes on the commands. The short version is in the [README](../README.en.md).

## First session

- The system keyring is Keychain on macOS and Secret Service on Linux desktops.

On the first session, the plugin installs its dependencies, pinned by hash, into its data directory.

- If that fails, masking still runs, but tokens show as `CPF#????????` and cannot be reversed.

To mask images, install `tesseract` (`apt install tesseract-ocr` or `brew install tesseract`).

## Check that it works

Run `pii-selfcheck` after installing, and again after every Claude Code update.

- An update can break masking without any error.
- It opens headless sessions with a fictitious CPF and reports what the model received.
- It needs the `claude` CLI and costs a few small model calls.

## Commands

| You want to | Command | Who runs it |
|---|---|---|
| Run a command with the real value | `pii-exec -- grep CPF#3f1a9c0d22e4 app.log` | Claude or you |
| Open a file with the real values | `pii-reveal report.md` | Claude or you |
| Read an XLSX | `pii-sheet file.xlsx` | Claude or you |
| Check that masking works | `pii-selfcheck` | Claude or you |
| Look up one token | `pii-unmask CPF#3f1a9c0d22e4` | only you |
| Stop masking a value for good | `pii-allow EMAIL#91bd0e4a7c13` | only you |

## The commands in your terminal

The `pii-*` commands are already on Claude's PATH. To run them in your own terminal, add this once to your shell profile:

```
export PATH="$HOME/.claude/plugins/data/pii-tokens-pii-tokens/bin:$PATH"
```

- `pii-unmask` and `pii-allow` only work this way: they run in an interactive terminal, so Claude cannot use them on its own.
- The folder is a link the plugin refreshes on every session, so it survives updates.

## Settings

All optional. Asked when the plugin is enabled, changed later with `claude plugin configure pii-tokens@pii-tokens`.

- **Allowed email domains:** domains left visible, such as your company's.
	- Allowed out of the box, with no setting: `example.com`, `example.org` and GitHub `noreply` addresses.
- **Tools that return tables:** prefixes of MCP tools that return a psql-style table, such as `mcp__postgres__`.
	- Their columns are masked by name (`nome`, `razao_social`, `email`, ...).
- **Copy the read request:** on by default. When a pasted image is blocked, the message asking Claude to read the file goes to the clipboard, replacing what was there.
- **Keep developer tool names:** off by default. See [Side effects](limits.en.md#side-effects).
- **Readable fields:** fields you know hold no person's name, in one tool. Format `tool:path`.
	- Example, to read task titles in a task tracker MCP: `mcp__tracker__:**.items[].name`, `mcp__tracker__:**.subitems[].name`, `mcp__tracker__:**.boards[].name`.
	- `**.` matches any start of the path.
	- A CPF, CNPJ, email or phone written inside the field still becomes a token.
	- The rule covers the whole tool. If the same account has a client board, its task titles, usually the client's name, come through too.
	- `[key=value]` before the last field filters by its neighbour: `mcp__tracker__:**.column_values[type=people].text` keeps only the people column, not the text columns.
- **Masked fields:** the opposite, for a field that holds personal data although its name does not say so. Same format.
	- Example, for a "Client" column: `mcp__tracker__:**.column_values[id=text_abc123].text`. The column id shows up in the tool's response.
	- ⚠️ Each tool of the same MCP may return a different shape. One may return columns as a list (the rule above) and another as a map: for it, `mcp__tracker__:**.column_values.text_abc123`. Add both, and check a real response before relying on them.
	- The board name may come in `boards[].name` from one tool and in `board.name` from the other.
	- The value becomes a token, and the same client always gets the same token, so tasks can be matched without seeing the name.
	- A field in both lists is masked.

## Notes on the commands

- **`pii-exec` masks the output again,** so the real value never comes back to Claude.
- **Every `pii-exec` with a token asks for your confirmation,** auto mode included. Read the command: `curl` or any network command would send the real value out, and a web page or a ticket can try to trick Claude into that.
	- While the command runs, the real value is visible in the process list (`ps`).
- **`pii-reveal` opens the copy in your editor,** outside Claude's reach.
- **`pii-allow` is for values that are fine to send:** your company's CNPJ, your own email in `git log`.
	- The allowlist keeps tokens, not values, so the config file holds no personal data.
	- `pii-allow --list` and `pii-allow --remove` manage it.
- **Text with personal data goes in a file, not in the prompt.** Save it and pass the path.
	- A prompt with a CPF, a CNPJ, a phone with area code or an email outside the allowed domains is blocked.
	- The block message brings the `pii-allow` command for each value.
	- `@file` is blocked too when the file has personal data, because `@` bypasses every hook.
- **Tokens stay out of your code.**
	- Before Claude writes a real token into a repository file or a commit message, you are asked.
	- Example tokens in documentation and files ignored by git are not affected.
	- This covers the write tools and `git commit`. Writing through the shell (`echo ... > file`, `tee`) is not checked.

The plugin also ships a skill that teaches Claude this workflow.

## Credit

The notes in [l-mb/claude-code-redaction-hooks](https://github.com/l-mb/claude-code-redaction-hooks) on which hooks can change what saved time here.

## Development

```
make test       # runs against a throwaway vault and config
```

`make install` copies the scripts to `~/.claude/hooks/pii`, for a setup without the plugin.

- That setup reads `~/.config/pii-tokens/config.json`.
- It takes the same keys as the plugin options, plus `data_dir` and `keyring_service`.
