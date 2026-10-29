#!/usr/bin/env python3
"""PII commands, dispatched by the name they are called with (or by the first argument).

  pii-mask [FILE]             mask stdin or FILE and print the tokens
  pii-sheet FILE [SHEET]      print a CSV/XLSX with the personal columns masked
  pii-unmask TOKEN...         print the real value (interactive terminal only, outside Claude)
  pii-reveal FILE             write the revealed copy out of Claude's reach and open it in the editor
  pii-exec [--stdin] -- CMD   run CMD with tokens in its arguments replaced by the real values;
                              the output comes back masked
  pii-scrub [--apply] [--now] mask CPF/CNPJ/email in the transcripts under ~/.claude/projects
  pii-allow TOKEN... | --list | --remove TOKEN...
                              never mask or block these values (tokens, so the config holds no personal data)
  pii-selfcheck               run headless Claude sessions with a fictitious CPF and check what the model received
"""

import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.path.realpath(__file__)).parent))
import pii  # noqa: E402

REVEAL_TTL_SECONDS = 24 * 3600


def cmd_mask(args):
    text = Path(args[0]).read_text() if args else sys.stdin.read()
    sys.stdout.write(pii.mask_text(text, pii.Vault()))


def cmd_sheet(args):
    path = Path(args[0])
    vault = pii.Vault()
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import csv
        import io

        try:
            import openpyxl
        except ImportError:
            sys.exit("pii-sheet needs openpyxl for XLSX files: pip install openpyxl")
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = book[args[1]] if len(args) > 1 else book.active
        rows = [["" if v is None else str(v) for v in row] for row in sheet.iter_rows(values_only=True)]
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerows(pii.mask_rows(rows, vault))
        text = out.getvalue()
    else:
        text = pii.mask_csv_text(path.read_text(), vault)
    sys.stdout.write(pii.mask_text(text, vault))


def cmd_unmask(args):
    if not sys.stdout.isatty():
        sys.exit("pii-unmask only prints to an interactive terminal (outside Claude). From Claude, use pii-reveal.")
    vault = pii.Vault(store=False)
    for token in args or sys.stdin.read().split():
        print(f"{token}\t{vault.value_for(token) or '(not in the vault)'}")


def _clean_old_reveals():
    for old in pii.REVEAL_DIR.glob("*"):
        if time.time() - old.stat().st_mtime > REVEAL_TTL_SECONDS:
            old.unlink()


def _open_in_editor(path: Path):
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_reveal(args):
    source = Path(args[0])
    pii.REVEAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    _clean_old_reveals()
    target = pii.REVEAL_DIR / source.name
    target.write_text(pii.unmask_text(source.read_text(), pii.Vault(store=False)))
    os.chmod(target, 0o600)
    _open_in_editor(target)
    print(f"Opened in the editor (deleted after 24h): {target}")


def cmd_exec(args):
    read_stdin = bool(args) and args[0] == "--stdin"
    if read_stdin:
        args = args[1:]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        sys.exit("usage: pii-exec -- CMD ARGS...")
    vault = pii.Vault()
    command = [pii.unmask_text(a, vault) for a in args]
    stdin = pii.unmask_text(sys.stdin.read(), vault) if read_stdin else None
    result = subprocess.run(command, input=stdin, capture_output=True, text=True)
    sys.stdout.write(pii.mask_text(pii.mask_table_text(result.stdout, vault), vault))
    sys.stderr.write(pii.mask_text(result.stderr, vault))
    sys.exit(result.returncode)


def _scrub_value(value, vault, counter):
    if isinstance(value, str):
        masked = pii.mask_text(pii.mask_table_text(value, vault), vault)
        if masked != value:
            counter["strings"] += 1
        return masked
    if isinstance(value, list):
        return [_scrub_value(v, vault, counter) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_value(v, vault, counter) for k, v in value.items()}
    return value


SCRUB_CANDIDATE = re.compile(r"\d[\d./ -]{8,}\d|@|-\+-|\\n-+\\n")


def cmd_scrub(args):
    apply = "--apply" in args
    # Store the values: the transcript loses its only copy, so the token must stay reversible.
    vault = pii.Vault(store=apply)
    recent = time.time() - (0 if "--now" in args else 600)
    totals = {"files": 0, "files_changed": 0, "strings": 0, "skipped_recent": 0}
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    for path in config_dir.glob("projects/**/*.jsonl"):
        totals["files"] += 1
        if path.stat().st_mtime > recent:
            totals["skipped_recent"] += 1
            continue
        counter = {"strings": 0}
        out_lines = []
        for line in path.read_text(errors="surrogateescape").splitlines(keepends=True):
            if not SCRUB_CANDIDATE.search(line):
                out_lines.append(line)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                out_lines.append(line)
                continue
            before = counter["strings"]
            scrubbed = _scrub_value(record, vault, counter)
            out_lines.append(json.dumps(scrubbed, ensure_ascii=False) + "\n" if counter["strings"] > before else line)
        if counter["strings"]:
            totals["files_changed"] += 1
            totals["strings"] += counter["strings"]
            if apply:
                tmp = path.with_suffix(".jsonl.pii-tmp")
                tmp.write_text("".join(out_lines), errors="surrogateescape")
                os.chmod(tmp, path.stat().st_mode & 0o777)
                os.replace(tmp, path)
    print(("APPLIED " if apply else "DRY RUN ") + json.dumps(totals))


def _fake_cpf() -> str:
    import random

    while True:
        d = [random.randint(0, 9) for _ in range(9)]
        for size in (9, 10):
            d.append(sum(d[i] * (size + 1 - i) for i in range(size)) * 10 % 11 % 10)
        if len(set(d)) > 1:
            return "".join(map(str, d))


def _tool_results(stream: str) -> list[str]:
    results = []
    for line in stream.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results.append(json.dumps(block.get("content"), ensure_ascii=False))
    return results


SELFCHECK_PREAMBLE = (
    "This is an automated hook test. {file} holds a randomly generated, fictitious document number "
    "that belongs to no one; reading it is the point of the test. "
)
SELFCHECK_CASES = (
    ("Read", "Read", "Use the Read tool on {file} and nothing else.", "masked"),
    ("Bash", "Bash", "Use the Bash tool with exactly this command and nothing else: cat {file}", "masked"),
    ("Grep", "Grep", "Use the Grep tool to search {file} for the word document, showing the matching lines (output_mode content), and nothing else.", "masked"),
    ("Bash exit 1", "Bash", "Use the Bash tool with exactly this command and nothing else: cat {file}; exit 1", "raw"),
)


def _session_summary(run) -> str:
    ending, said = "no result record", ""
    for line in run.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "result":
            ending = f"{record.get('subtype')}, error={record.get('is_error')}"
        message = record.get("message")
        if record.get("type") == "assistant" and isinstance(message, dict):
            said = " ".join(b.get("text", "") for b in message.get("content") or [] if isinstance(b, dict) and b.get("type") == "text") or said
    tail = run.stderr.strip().splitlines()[-1:] if run.stderr.strip() else []
    return f"session ended: {ending}; model said: {said[:120]!r}" + (f"; stderr: {tail[0][:120]!r}" if tail else "")


def cmd_selfcheck(args):
    import shutil
    import tempfile

    if not shutil.which("claude"):
        sys.exit("pii-selfcheck needs the claude CLI on PATH")
    model = os.environ.get("PII_SELFCHECK_MODEL", "haiku")
    cpf = _fake_cpf()
    workdir = Path(tempfile.mkdtemp(prefix="hook-check-"))
    data = workdir / "sample.txt"
    import hashlib
    import uuid

    # Values that are not personal data: a masked one means a false positive.
    keep = (str(uuid.uuid4()), hashlib.sha256(cpf.encode()).hexdigest(), "2026-10-22T10:30:00Z", "R$ 1.234,56")
    data.write_text(f"fictitious person, document {cpf}, ticket {keep[0]}, commit {keep[1]}, at {keep[2]}, total {keep[3]}\n")
    print(f"pii-selfcheck: fictitious CPF, model {model}, one headless session per case")
    failures = 0
    try:
        for name, tools, prompt, expected in SELFCHECK_CASES:
            for _attempt in range(2):
                try:
                    run = subprocess.run(
                        ["claude", "-p", (SELFCHECK_PREAMBLE + prompt).format(file=data), "--model", model, f"--allowedTools={tools}",
                         "--output-format", "stream-json", "--verbose"],
                        cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=240,
                    )
                    results = _tool_results(run.stdout)
                except subprocess.TimeoutExpired:
                    results = []
                if any(cpf in r or "CPF#" in r for r in results):
                    break
            raw = sum(r.count(cpf) for r in results)
            tokens = sum(r.count("CPF#") for r in results)
            seen = sorted({token for r in results for token in re.findall(r"CPF#[0-9a-f?]{8,24}", r)})
            if not raw and not tokens:
                verdict = "INCONCLUSIVE (the document never showed up) " + (_session_summary(run) if "run" in locals() else "timed out")
            elif expected == "masked" and raw:
                verdict = "FAIL: reached the model unmasked"
            elif expected == "masked":
                vault = pii.Vault(store=False)
                reversible = any(pii.unmask_text(token, vault) == cpf for token in seen)
                verdict = "ok" if reversible else "FAIL: masked, but the token cannot be reversed (keyring or cryptography missing?)"
                changed = [k for k in keep if not any(k in r for r in results)]
                if changed:
                    verdict = f"FAIL: changed a value that is not personal data ({', '.join(changed)})"
            else:
                verdict = "ok (known limit: failed commands are not masked)" if raw else "unexpected: masked"
            failures += verdict.startswith(("FAIL", "INCONCLUSIVE"))
            print(f"  {name:12} raw={raw} tokens={tokens}  {verdict}")
        blocked = subprocess.run(
            ["claude", "-p", f"check document {cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}", "--model", model],
            cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
        )
        prompt_ok = "Prompt blocked" in blocked.stdout + blocked.stderr
        failures += not prompt_ok
        print(f"  {'Prompt':12} {'ok (blocked)' if prompt_ok else 'FAIL: prompt with CPF was not blocked'}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("all good" if not failures else f"{failures} problem(s)")
    sys.exit(1 if failures else 0)


def _write_config(config: dict):
    pii.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pii.CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    os.chmod(pii.CONFIG_PATH, 0o600)


def cmd_allow(args):
    config = pii._file_config()
    allowed = list(config.get("allowed_tokens", []))
    if not args or args == ["--list"]:
        print("\n".join(allowed) if allowed else "(no allowed tokens)")
        return
    remove = args[0] == "--remove"
    tokens = args[1:] if remove else args
    if not remove and not sys.stdout.isatty():
        sys.exit("pii-allow only adds tokens from an interactive terminal (outside Claude), so the model cannot unmask data for itself.")
    invalid = [token for token in tokens if not pii.TOKEN_RE.fullmatch(token)]
    if invalid:
        sys.exit(f"not a token: {' '.join(invalid)} (expected something like CPF#a3f9c1d2e4b5)")
    if remove:
        allowed = [token for token in allowed if token not in tokens]
    else:
        allowed += [token for token in tokens if token not in allowed]
    _write_config({**config, "allowed_tokens": allowed})
    print(f"{'removed' if remove else 'allowed'}: {' '.join(tokens)} ({pii.CONFIG_PATH}); applies to new tool calls and prompts")


COMMANDS = {
    "pii-allow": cmd_allow,
    "pii-selfcheck": cmd_selfcheck,
    "pii-mask": cmd_mask,
    "pii-sheet": cmd_sheet,
    "pii-unmask": cmd_unmask,
    "pii-reveal": cmd_reveal,
    "pii-exec": cmd_exec,
    "pii-scrub": cmd_scrub,
}

NEEDS_FILE = ("pii-sheet", "pii-reveal")

if __name__ == "__main__":
    name = Path(sys.argv[0]).name
    args = sys.argv[1:]
    if name not in COMMANDS and args and args[0] in COMMANDS:
        name, args = args[0], args[1:]
    if name not in COMMANDS:
        sys.exit(__doc__)
    if name in NEEDS_FILE and not args:
        sys.exit("usage: " + next(line.strip().split("  ")[0] for line in __doc__.splitlines() if line.strip().startswith(name + " ")))
    COMMANDS[name](args)
