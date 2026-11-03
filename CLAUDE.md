# pii-tokens

Claude Code plugin that swaps personal data (CPF, CNPJ, email, phone, names) for tokens before the model sees it. Users install only `plugin/`; `desktop/` is the Claude Desktop chat extension.

## Commands

- Tests: `make test`. Read the exit code and the `FAIL` lines; the number of `ok` lines changes when a PR adds tests.
- Desktop extension tests with the proxy: `desktop/.venv/bin/python tests/test_desktop.py` (without `fastmcp` they print `skip`).
- Plugin manifest: `claude plugin validate plugin`.
- The branch in a real session: `claude --plugin-dir plugin --settings '{"enabledPlugins":{"pii-tokens@pii-tokens":false}}'`. Judge masking by counting the exact planted value in the raw `tool_result` (`--output-format stream-json --verbose`), with the unmasked source as control; a pattern count (any 11 digits) also matches times and ids.

## Conventions

- Before a PR, read `CONTRIBUTING.md`: it holds the PR rules (version bump, docs in both languages, new options off by default, `Fixes` vs `Refs`).
- A change to what gets masked runs the old and the new code on the same inputs; the PR states how many outputs changed and gives examples with made-up data.
- A "kept" (not masked) assertion sits next to a test where the same detector does mask.
- A detector change gets tests at its edges: the shapes it must catch whole (hyphenated, joined, longer forms) and the ones it must leave alone.
- Masking more has a cost: check that Claude can still use the value in its next call (a branch name in a git command, a filter in a query). A token where a tool needs the real value breaks the workflow.
- A PR that says it works somewhere (Windows, Desktop Code, Desktop chat) was run there; the PR lists where it was not.
- Docs point to where a value lives (a file, a command) instead of copying numbers, versions or lists from it.

## Gotchas

- With the plugin installed, reading this repo shows the plugin masking its own fixtures (names in manifests, the name list in `pii.py` when the names option is on): edit those lines with a script that reads the real file.
- The hook fails closed: when masking errors or times out, the output is suppressed, not passed through (`plugin/scripts/hook.py`).
- The Desktop extension bundles its own copy of `plugin/scripts/pii.py` (`desktop/build.py`): a masking change reaches the chat only with a new extension package and a bump in `desktop/manifest.json`.
