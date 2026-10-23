# Alternatives

Surveyed on 2026-10-14 by reading each project's README, and rechecked and extended on 2026-10-22. We installed none of them. Found a mistake or a missing project? Open an issue.

[Leia em português](alternativas.md)

## What sets pii-tokens apart

- **It swaps, it doesn't block.** Claude keeps working with the token in place of the value.
- **Reversible on your machine.** The vault is encrypted and the key sits in the system keyring.
- **Brazilian documents.** CPF and CNPJ, alphanumeric CNPJ included, with check digits.
- **No local AI model.** Regex and validation only: installs in seconds and downloads no model.

## Comparison

| Project | What it is | CPF/CNPJ | Inside Claude Code | Reversible | Where it beats pii-tokens |
|---|---|---|---|---|---|
| Claude Enterprise inference hooks, with Netskope, Palo Alto, Proofpoint or Zscaler | company DLP, in beta since August 2026 | depends on the vendor | yes, Enterprise plan only | no: allow or block | central policy for the whole company |
| [tarja](https://github.com/macmaia/tarja) | Python library | yes, plus 15 more Brazilian types | no | yes, in memory | more document types, uses the sentence context |
| [lgpd-guard](https://github.com/arthurpenedo/lgpd-guard) | OpenAI-compatible proxy, CLI and library | yes | no | yes, per session | finds names with NER |
| [claude-privacy-tool](https://github.com/pasqualepillitteri/claude-privacy-tool) | prompt hook and MCP server, with a 1.5B model | not mentioned | yes | yes | finds names and addresses in free text |
| [noirdoc](https://github.com/noirdoc-ai/mask-claude-plugin) | plugin that blocks reads and redacts a copy | no (German first) | yes | yes, outside the session | reads PDF, PPTX and images |
| [claude-code-redaction-hooks](https://github.com/l-mb/claude-code-redaction-hooks) | regex hooks | no | yes | not confirmed | focused on secrets, several actions per rule |
| [redact-hook](https://github.com/SilentAutomaton/redact-hook) | one file, regex only | no | yes | no | zero dependencies |
| [nopii](https://github.com/olafrv/nopii) | proxy via `ANTHROPIC_BASE_URL` | no | through a proxy: messages and tool output | yes | finds names with GLiNER |
| [claude-code-redact](https://github.com/paroque28/claude-code-redact) | local proxy | not mentioned | through a proxy | yes | secrets and NDA material, per-project rules |
| [JanuScope](https://github.com/giancarloerra/JanuScope) | MCP proxy with a YAML policy | no | MCP tools only | no: swaps for `[REDACTED]` | hides dangerous tools, gates SQL writes, audit log; works with clients beyond Claude Code |

## When pii-tokens is the wrong pick

- You need one central policy for the whole company: use the Enterprise inference hooks.
- You need names found in free text: here a name is masked only in a field named like a person, in a table or JSON.
- You don't use Claude Code: `tarja` or `lgpd-guard` fit any codebase.
