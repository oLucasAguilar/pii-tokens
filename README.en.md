# pii-tokens

**Personal data out of Claude's context.**

A Claude Code plugin. Before Claude reads them, it swaps for tokens:

- Brazilian IDs (CPF, CNPJ), email and phone numbers.

- Same value, same token: Claude can still count, join and compare.
- The real value stays in an encrypted vault on your machine.

It reduces accidental leaks, it does not eliminate them. Before using it with real data, read the [limits](#limits).

| Where you use Claude | Status |
|---|---|
| Claude Code (terminal or IDE) | ✅ Available: follow [Install](#install) |
| Claude Desktop chat | 🚧 In development, for what connectors (MCP) return. What you paste or attach is not masked: swap names, CPFs and emails for nicknames |
| claude.ai | Not supported: swap names, CPFs and emails for nicknames before pasting or attaching |

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/demo.gif"><img alt="Claude reads a CSV with names, CPFs and emails and gets tokens; a CPF pasted into the prompt is blocked (screen in Portuguese)" src="docs/demo-light.gif"></picture>

[Leia em português](README.md)

## Install

```
/plugin marketplace add oLucasAguilar/pii-tokens
/plugin install pii-tokens@pii-tokens
```

1. Restart Claude Code.
2. Ask Claude to "run `pii-selfcheck`". It must end with `all good`.

Needs Linux or macOS and Python 3.10+. Images also need `tesseract`.

## In practice

**A database query**

The real value is used only after you confirm.

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/demo-banco.gif"><img alt="The query returns company names and CNPJs and Claude gets tokens; pii-exec asks for confirmation before using the real value (screen in Portuguese)" src="docs/demo-banco-light.gif"></picture>

**Text in a file**, like a note or an email

```diff
- CPF <real CPF>, contact <real email>. Spoke with Maria.
+ CPF CPF#3f1a9c0d22e4, contact EMAIL#91bd0e4a7c13. Spoke with Maria.
```

A bare name in free text gets through: swap it for a nickname, or add it to the term list.

**Claude's tools**, like Jira, Notion, a CRM or an internal API

You choose which fields stay readable.

```diff
  title: "Login error"               assignee: "A Teammate"
- client: "Acme Comercio Ltda"
+ client: "NAME#25aaae7143ac"
```

**Images**

- The hook reads the image text before Claude sees it, and draws tokens over the values.
- A pasted image with personal data blocks the message:
	- a `Read <file>` request lands in your clipboard;
	- paste it and send.

**When you need the real value**

```bash
pii-exec -- grep CPF#3f1a9c0d22e4 app.log   # uses the real CPF; the output comes back masked
pii-reveal report.md                        # opens the real version in your editor, away from Claude
```

Commands and settings: [docs/usage.en.md](docs/usage.en.md).

## What gets masked

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/tokens-en-dark.gif"><img alt="A CPF and an email turn into tokens" src="docs/tokens-en-light.gif"></picture>

| Data | Token |
|---|---|
| CPF and CNPJ (with valid check digits) | `CPF#`, `CNPJ#` |
| Email, outside the domains you allow | `EMAIL#` |
| Brazilian phone numbers | `PHONE#` |
| Name, contact and document columns (table, CSV, JSON) | `NAME#`, `CONTACT#`, `DOC#` |
| Terms you list, such as a client's name | `TERM#` |
| IP addresses, if you turn the option on | `IP#` |

## Limits

It protects against accidental leaks, not against a model set on extracting the data.
Whatever the detector does not recognize goes through as is: review before sending sensitive data.

These get through unmasked:

- names in free text outside the term list;
- failing commands and `!` commands;
- keys, passwords and API tokens (the plugin handles personal data).

Also:

- In images, OCR finds almost every CPF and CNPJ, not all of them.
- A token is a pseudonym, not anonymous.

Full list, before using it with real data: [docs/limits.en.md](docs/limits.en.md).

## What about the others?

On 2026-10-22 we found no other tool that:

- swaps data for a reversible token;
- understands Brazilian documents;
- runs inside Claude Code.

Comparison: [docs/alternatives.md](docs/alternatives.md).
