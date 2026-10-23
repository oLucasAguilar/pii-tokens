# Contribuir / Contributing

Issues e PRs são bem-vindos, em português ou inglês. / Issues and PRs are welcome, in Portuguese or English.

- **Nunca use dado real** em issue, teste, exemplo ou commit: gere valores (os testes geram CPF e CNPJ na hora). / **Never use real personal data**: generate values, as the tests do.
- **Falha de segurança** (dado pessoal chegando ao modelo por um caminho fora de [docs/limits.md](docs/limits.md)): reporte em privado, veja [SECURITY.md](SECURITY.md). / **Security issues**: report privately, see [SECURITY.md](SECURITY.md).
- **Rodar os testes / Run the tests:** `make test`. O CI roda o mesmo em Linux e macOS, Python 3.10 e 3.13. / CI runs the same on Linux and macOS, Python 3.10 and 3.13.
- **Mudou comportamento?** Atualize `docs/` nas duas línguas. / **Changed behaviour?** Update `docs/` in both languages.
- Um formato novo de documento precisa de um teste que mascara e de um que **não** mascara (número de pedido, data, hash). / A new document format needs a test that masks it and one that must **not** mask (order number, date, hash).
