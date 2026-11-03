# Contribuir / Contributing

Issues e PRs são bem-vindos, em português ou inglês. / Issues and PRs are welcome, in Portuguese or English.

- **Nunca use dado real** em issue, teste, exemplo ou commit: gere valores (os testes geram CPF e CNPJ na hora); email de exemplo em `.test` ou `.example`. / **Never use real personal data**: generate values, as the tests do; example emails under `.test` or `.example`.
- **Falha de segurança** (dado pessoal chegando ao modelo por um caminho fora de [docs/limits.md](docs/limits.md)): reporte em privado, veja [SECURITY.md](SECURITY.md). / **Security issues**: report privately, see [SECURITY.md](SECURITY.md).
- **Rodar os testes / Run the tests:** `make test`. O CI roda o mesmo. / CI runs the same.
- **Mudou comportamento?** Atualize `docs/` e o README, nas duas línguas. / **Changed behaviour?** Update `docs/` and the README, in both languages.
- **Mudou o plugin?** Suba `version` em `plugin/.claude-plugin/plugin.json`: sem isso, quem já usa não recebe a mudança. Na extensão do Desktop, o mesmo em `desktop/manifest.json`. / **Changed the plugin?** Bump `version` in `plugin/.claude-plugin/plugin.json`: without it, existing installs do not get the change. For the Desktop extension, the same in `desktop/manifest.json`.
- **Opção nova começa desligada**, para nada mudar para quem já usa. / **A new option starts off**, so nothing changes for existing users.
- Um formato novo de documento precisa de um teste que mascara e de um que **não** mascara (número de protocolo, data, hash). / A new document format needs a test that masks it and one that must **not** mask (ticket number, date, hash).
- **Fechar issue:** `Fixes #N` só quando o PR resolve a issue em todos os lugares dos labels dela; resolvendo parte, use `Refs #N`. / **Closing issues:** `Fixes #N` only when the PR solves the issue in every place its labels name; for part of it, use `Refs #N`.
- **Ajustes do mantenedor:** ajuste pequeno (versão, doc, conserto curto) pode entrar como commit do mantenedor na sua branch, explicado no PR. Deixe marcado "Allow edits by maintainers". / **Maintainer edits:** a small fix (version, docs, a short fix) may land as a maintainer commit on your branch, explained in the PR. Keep "Allow edits by maintainers" checked.
