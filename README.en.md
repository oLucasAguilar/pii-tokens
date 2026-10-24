# pii-tokens

**Personal data out of Claude's context.**

A Claude Code plugin. It swaps Brazilian personal data (CPF, CNPJ), email and phone numbers for tokens before Claude reads them. Same value, same token: Claude can still count, join and compare. The real value stays in an encrypted vault on your machine.

![Claude reads a CSV with names, CPFs and emails and gets tokens; a CPF pasted into the prompt is blocked (screen in Portuguese)](docs/demo.gif)

[Leia em português](README.md)

## Install

```
/plugin marketplace add oLucasAguilar/pii-tokens
/plugin install pii-tokens@pii-tokens
```

Restart and ask Claude to "run `pii-selfcheck`". It must end with `all good`. Linux or macOS, Python 3.10+.

## In practice

**A database query, and the real value only after you confirm**

![The query returns company names and CNPJs and Claude gets tokens; pii-exec asks for confirmation before using the real value (screen in Portuguese)](docs/demo-banco.gif)

**A support ticket saved to a file**

```diff
- CPF <real CPF>, contact <real email>. Spoke with Maria.
+ CPF CPF#3f1a9c0d22e4, contact EMAIL#91bd0e4a7c13. Spoke with Maria.
```

A bare name in free text gets through: swap it for a nickname.

**A Monday board:** you choose what stays readable

```diff
  name: "Boleto not settled"        assignee: "A Teammate"
- client: "Padaria Exemplo LTDA"
+ client: "NAME#25aaae7143ac"
```

**When you need the real value**

```bash
pii-exec -- grep CPF#3f1a9c0d22e4 app.log   # runs with the real CPF; the output comes back masked
pii-reveal report.md                        # opens the real version in your editor, away from Claude
```

**Screenshots**

An image Claude reads, from a file or the browser, arrives with the token drawn over the CPF and CNPJ. A screenshot pasted into the message is blocked, and the request to read the file goes to your clipboard: paste and send. Needs `tesseract`.

Commands and settings: [docs/usage.en.md](docs/usage.en.md).

## What gets masked

| Data | Token |
|---|---|
| CPF and CNPJ (with valid check digits) | `CPF#`, `CNPJ#` |
| Email, outside the domains you allow | `EMAIL#` |
| Brazilian phone numbers | `PHONE#` |
| Name, contact and document columns (table, CSV, JSON) | `NAME#`, `CONTACT#`, `DOC#` |

## Limits

It protects against accidental leaks, not against a model set on extracting the data.

- Names in free text, failing commands and `!` commands get through.
- In images, OCR finds almost every CPF and CNPJ, not all of them.
- Keys, passwords and API tokens get through: the plugin handles personal data.
- A token is a pseudonym, not anonymous.

Full list, before using it with real data: [docs/limits.en.md](docs/limits.en.md).

## What about the others?

On 2026-10-22 we found no other tool that swaps data for a reversible token, understands Brazilian documents and runs inside Claude Code. Comparison: [docs/alternatives.md](docs/alternatives.md).
