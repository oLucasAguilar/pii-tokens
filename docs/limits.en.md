# Limits

What pii-tokens does not protect, what strict masking costs, and what stays unmasked on your disk. Read it before using the plugin with real personal data.

This protects against accidental exposure, not against a model trying to extract data. Claude runs commands as you: a determined model, or one steered by a malicious text, can read the keyring and open the vault, just as the plugin does.

- In our tests, a model could not edit a line that held a masked CPF.
- It then printed the file with `od -c` and read the digits.
- On 2026-10-22, with prompts built to extract it, the CPF also came out reversed (`rev`) and with spaces between the digits. A plain read, the whole file and base64 did not leak.
- Comparison also reveals: the same value always gives the same token, so someone who already knows part of a CPF can print numbered candidates and find the one that matches.

## What gets through

- **Commands that fail reach the model raw.**
	- The hook Claude Code fires on failure cannot change the output.
	- Requested in [anthropics/claude-code#97278](https://github.com/anthropics/claude-code/issues/97278).
- **Names in free text are not detected:** issue bodies, web pages, log lines.
- **Some document shapes are not detected:**
	- a phone written as 11 bare digits, unless it sits in a phone column
	- a CPF glued to letters, such as `doc` followed by the digits
	- a CPF broken across two lines
	- a CPF written with dots only (`123.156.189.09`) whose first three blocks are 255 or less: it looks like an IP and passes (about 2% of that shape; with a hyphen, always masked)
- **Secrets are not masked:** API keys, passwords, access tokens, connection strings. The plugin handles personal data; for secrets, run a secrets tool alongside it ([alternatives](alternatives.md)).
- **`!` commands skip every hook.**
	- Their output goes straight into the context, and they cannot be blocked.
- **Images are not masked.** A screenshot of a page with a CPF goes through.
- **A query built to dodge the field names gets through.**
	- A SQL function, such as `SELECT reverse(cpf)`.
	- A renamed field, such as `title: name` in GraphQL or `AS title` in SQL.
- **Telemetry sees the original.**
	- Claude Code records tool output for OpenTelemetry before hooks run.

One thing fails closed: if masking takes more than 25 seconds or crashes, the output is suppressed, not passed through.

## Side effects

Masking is strict by default. That costs when the data on screen is not personal data:

- **JSON `name` fields are always masked.**
	- In `package.json`, `kubectl get -o json` or `docker inspect`, Claude sees `NAME#...` instead of the name.
	- Turn on **Keep developer tool names** to leave those fields alone.
	- For task titles (Monday, Asana, Trello), use **Readable fields** ([usage](usage.en.md#settings)).
	- A field is kept only inside a document shaped exactly like one of those tools.
	- So `{"name": "Maria Silva", "scripts": {}}` is still masked.
	- What it lets through is a one-word name inside such a document.
- **A `person`, `people` or `pessoas` field becomes a token by default** (a Monday assignee, for example). To read it, use **Readable fields**.
- **About 1 in 100 random numbers of 11 or 14 digits become tokens.**
	- They pass the CPF or CNPJ check digits: order ids, phone numbers without punctuation, the last block of a Brazilian boleto line.
	- Run the command that needs the number through `pii-exec`.
- **Each tool call pays for one Python process.**
	- About 0.3 s for masking and 0.04 s for the write check, measured on a laptop.

## What stays on disk

Masking decides what reaches the model. On your own disk, some copies stay unmasked:

- **Transcripts** (`~/.claude/projects/`) record these as they came:
	- a blocked prompt
	- the output of a failed command
	- Masked outputs are recorded masked.
	- `pii-scrub --apply` rewrites old transcripts with tokens.
- **Large outputs:** above 50 KB, Claude Code saves the full output next to the transcript.
	- What the model reads from it is masked; the file is not.
- **Revealed copies:** `pii-reveal` writes plaintext to `~/.cache/pii-tokens/reveal`, readable only by you.
	- They are deleted after 24 hours, when a session starts or `pii-reveal` runs.
- **The vault** is encrypted, with the key in your system keyring.
	- That protects a stolen disk or a leaked backup, not a program running as you.

## Network and LGPD

- **Once installed, the plugin makes no network calls.** Masking, vault and tokens stay on your machine. Installing downloads `keyring` and `cryptography`, checked by hash.
- **A token is a pseudonym, not anonymous.** It is stable and links the records of the same person; under LGPD and GDPR, pseudonymized data is still personal data.
- **It is not an LGPD (or GDPR) compliance certificate.** It reduces the personal data sent to the API; what may be sent is still your call.
