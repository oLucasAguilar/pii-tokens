# Security

Em português: achou um jeito de dado pessoal chegar ao modelo? Reporte em **Report a vulnerability**, na aba Security, nunca numa issue pública, e use um CPF inventado.

pii-tokens exists to keep personal data away from the model, so a way around it is a security problem.

## Reporting

Use **Report a vulnerability** in this repository's Security tab. It opens a private advisory that only the maintainer sees.

Do not open a public issue for it, and do not paste real personal data in the report: a fictitious CPF (any number that passes the check digit) reproduces every case.

Worth reporting:

- personal data that reaches the model through a path not listed in [docs/limits.en.md](docs/limits.en.md)
- a token that can be reversed without the system keyring
- a real token written into a repository file without the approval prompt

What `docs/limits.en.md` already lists (failed commands, free-text names, images, `!` commands) is known.

## Versions

Only the latest version gets fixes.

Releases come only from `main`, which is protected: every change goes through a reviewed pull request with the tests passing.
