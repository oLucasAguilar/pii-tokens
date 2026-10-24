#!/usr/bin/env python3
"""Claude Code hooks that keep personal data out of the model context.

  hook.py post    PostToolUse: masks the output of every tool, images included (OCR)
  hook.py prompt  UserPromptSubmit: blocks prompts carrying CPF/CNPJ, pasted images or @-mentioned files with PII
  hook.py pre     PreToolUse: asks before a live token is written into a repository file or a commit message
"""

import json
import re
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PROMPT_ESCAPE = "pii-ok"
DEADLINE_SECONDS = 25
SPREADSHEET_SUFFIXES = (".csv", ".tsv")
SHAPE_KEYS = ("type", "mode")
AT_MENTION = re.compile(r"(?:^|(?<=\s))@(\"[^\"]+\"|\S+)")
AT_MENTION_MAX_BYTES = 5_000_000
BLANK_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
IMAGE_UNCHECKED = (
    "[pii-tokens] This image was not checked for personal data: install tesseract (and Pillow in the plugin venv) "
    "to have CPF, CNPJ, e-mail and phone in images replaced by tokens."
)


def emit(payload: dict) -> None:
    print(json.dumps(payload))


def _git_tracked(path: str) -> bool:
    file = Path(path)
    if not file.is_file():
        return False
    result = subprocess.run(
        ["git", "-C", str(file.parent), "ls-files", "--error-unmatch", file.name],
        capture_output=True,
    )
    return result.returncode == 0


def _mask_spreadsheet_read(pii, event: dict, response, vault):
    path = event.get("tool_input", {}).get("file_path", "")
    file = response.get("file") if isinstance(response, dict) else None
    if event.get("tool_name") != "Read" or not path.lower().endswith(SPREADSHEET_SUFFIXES) or not isinstance(file, dict):
        return response
    return {**response, "file": {**file, "content": pii.mask_csv_text(file.get("content", ""), vault)}}


def _suppress(value, notice: str):
    if isinstance(value, str):
        return notice
    if isinstance(value, list):
        return [_suppress(v, notice) for v in value]
    if isinstance(value, dict):
        return {k: v if k in SHAPE_KEYS else _suppress(v, notice) for k, v in value.items()}
    return value


def _deadline_reached(signum, frame):
    raise TimeoutError(f"masking took longer than {DEADLINE_SECONDS}s")


def _mask_images(image, response, vault):
    """The response with its images masked (blank when masking fails), and the note for Claude."""
    if not image.available():
        return response, IMAGE_UNCHECKED
    try:
        masked, labels = image.mask_images(response, vault)
    except Exception as e:
        # The output must keep the image shape, or Claude Code falls back to the original.
        return image.blank_images(response, BLANK_PNG), f"[pii-tokens] image withheld: masking failed ({type(e).__name__}: {e})"
    if not labels:
        return masked, None
    return masked, "[pii-tokens] Personal data in this image was replaced by tokens (OCR, best effort): " + ", ".join(
        dict.fromkeys(labels)
    )


def post(event: dict) -> None:
    tool = event.get("tool_name", "")
    if tool == "Read" and _git_tracked(event.get("tool_input", {}).get("file_path", "")):
        return
    response = event.get("tool_response")
    signal.signal(signal.SIGALRM, _deadline_reached)
    signal.alarm(DEADLINE_SECONDS)
    with_images, note = False, None
    try:
        import image
        import pii

        with_images = image.has_image(response)
        vault = pii.Vault()
        if with_images:
            response_images, note = _mask_images(image, response, vault)
            text_only = image.replace_images(response_images, "")  # base64 is never text to mask
        else:
            text_only = response
        tables = bool(pii.TABLE_TOOLS) and tool.startswith(pii.TABLE_TOOLS)
        masked = pii.mask_json(_mask_spreadsheet_read(pii, event, text_only, vault), vault, tables, tool)
        if with_images:
            masked = image.restore_images(masked, response_images)
    except Exception as e:
        masked = _suppress(response, f"[pii-tokens] output suppressed: masking failed ({type(e).__name__}: {e})")
        if with_images:
            masked = image.blank_images(masked, BLANK_PNG)
    if masked == response and not note:
        return
    output = {"hookEventName": "PostToolUse", "updatedToolOutput": masked}
    if note:
        output["additionalContext"] = note
    emit({"hookSpecificOutput": output})


def _mentioned_files_with_pii(pii, text: str, cwd: str) -> list[str]:
    vault = pii.Vault(store=False)
    found = []
    for raw in AT_MENTION.findall(text):
        path = Path(raw.strip('"')).expanduser()
        path = path if path.is_absolute() else Path(cwd) / path
        if not path.is_file() or _git_tracked(str(path)):
            continue
        if path.stat().st_size > AT_MENTION_MAX_BYTES:
            found.append(raw)
            continue
        content = path.read_text(errors="ignore")
        masked = pii.mask_csv_text(content, vault) if path.suffix.lower() in SPREADSHEET_SUFFIXES else content
        if pii.mask_text(pii.mask_json_text(masked, vault), vault) != content:
            found.append(raw)
    return found


CLIPBOARD_COMMANDS = (["wl-copy"], ["xclip", "-selection", "clipboard"], ["pbcopy"])


def _copy_to_clipboard(text: str) -> bool:
    import shutil

    for command in CLIPBOARD_COMMANDS:
        if not shutil.which(command[0]):
            continue
        try:
            done = subprocess.run(command, input=text.encode(), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            return True
    return False


def _pasted_images_to_block(event: dict) -> tuple[list[str], bool]:
    """Pasted images that hold personal data, or that could not be checked; and whether OCR is missing."""
    import image

    paths = image.pasted_images(event)
    if not paths:
        return [], False
    if not image.available():
        return [], True
    # Claude Code sends the prompt when the hook times out, so the hook must give up first and block.
    signal.signal(signal.SIGALRM, _deadline_reached)
    signal.alarm(DEADLINE_SECONDS)
    blocked = []
    for i, path in enumerate(paths):
        try:
            if image.has_personal_data(path.read_bytes()):
                blocked.append(str(path))
        except TimeoutError:
            blocked.extend(str(p) for p in paths[i:])
            break
        except Exception:
            blocked.append(str(path))
    signal.alarm(0)
    return blocked, False


def prompt(event: dict) -> None:
    import pii

    text = event.get("prompt", "")
    if PROMPT_ESCAPE in text:
        return
    mentioned = _mentioned_files_with_pii(pii, text, event.get("cwd", "."))
    if mentioned:
        emit({
            "decision": "block",
            "reason": (
                f"[pii-tokens] Prompt blocked: {', '.join(mentioned)} contains personal data, and a file "
                "mentioned with @ enters the context without passing through masking. Write the path "
                f"without the @ and ask for it to be read. To send anyway, include `{PROMPT_ESCAPE}`."
            ),
        })
        return
    images, unchecked = _pasted_images_to_block(event)
    if images:
        import image

        request = f"Read {' and '.join(images)}. {image.PASTED_IMAGE.sub('', text).strip()}".strip()
        copied = pii.COPY_READ_REQUEST and _copy_to_clipboard(request)
        emit({
            "decision": "block",
            "reason": (
                "[pii-tokens] Prompt blocked: a pasted image holds personal data (or could not be checked in time), "
                "and a pasted image reaches "
                "Claude as it is; reading the file instead replaces the data with tokens. "
                + ("The message below is in your clipboard: clear the prompt, paste it and send.\n\n"
                   if copied else "Clear the prompt and send:\n\n")
                + f"{request}\n\nTo send the image anyway, include `{PROMPT_ESCAPE}`."
            ),
        })
        return
    vault = pii.Vault(store=False)
    text = pii.normalize_pasted_documents(text)
    found = [("CPF", m) for m in pii.CPF_FORMATTED.findall(text) + pii.DIGITS_11.findall(text)
             if pii.valid_cpf(m) and not pii.looks_like_ipv4(m)]
    found += [("CNPJ", m) for m in pii.CNPJ_FORMATTED.findall(text) + pii.DIGITS_14.findall(text) if pii.valid_cnpj(m)]
    found += [("EMAIL", m.group(0)) for m in pii.EMAIL_RE.finditer(text) if pii.is_personal_email(m)]
    found += [("PHONE", m.group(0)) for m in pii.PHONE_RE.finditer(text)]
    found += [("PHONE", m.group(0)) for m in pii.PHONE_BARE_AREA_CODE.finditer(text) if m.group(1) in pii.AREA_CODES]
    blocked = sorted({vault.token_for(kind, value) for kind, value in found if not vault.is_allowed(kind, value)})
    if blocked:
        emit({
            "decision": "block",
            "reason": (
                f"[pii-tokens] Prompt blocked: it contains personal data ({', '.join(blocked)}). Put the text "
                "in a file and pass the path (reading it masks the data). If a value is fine to send, allow it "
                f"once and for all by running, in your own terminal, `pii-allow {' '.join(blocked)}`. To send this prompt anyway, include "
                f"`{PROMPT_ESCAPE}`."
            ),
        })
    elif unchecked:
        emit({"systemMessage": IMAGE_UNCHECKED})


WRITE_FIELDS = ("content", "new_string", "new_source")
GIT_COMMIT = re.compile(r"\bgit\b[^|;&\n]*\bcommit\b")


def _in_repository_and_not_ignored(path: str) -> bool:
    folder = Path(path).parent
    while not folder.is_dir() and folder != folder.parent:
        folder = folder.parent
    inside = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True)
    if inside.returncode != 0:
        return False
    return subprocess.run(["git", "-C", str(folder), "check-ignore", "-q", path], capture_output=True).returncode != 0


PII_EXEC = re.compile(r"(?<![\w-])pii-exec\b")


def _asks_for_real_values(command: str) -> bool:
    import pii

    if "--stdin" not in command and not pii.TOKEN_RE.search(command):
        return False
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": (
            "[pii-tokens] pii-exec runs this command with the real values in place of the tokens. "
            "Approve only if you know where the command sends them (a network command would send the "
            "personal data out). This also asks in auto mode."
        ),
    }})
    return True


def pre(event: dict) -> None:
    tool, tool_input = event.get("tool_name", ""), event.get("tool_input", {})
    if tool == "Bash":
        text = tool_input.get("command", "")
        if PII_EXEC.search(text) and ("#" in text or "--stdin" in text) and _asks_for_real_values(text):
            return
        target = "a commit message" if GIT_COMMIT.search(text) else ""
    else:
        text = " ".join(str(tool_input.get(field, "")) for field in WRITE_FIELDS)
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        target = path if path and "#" in text and _in_repository_and_not_ignored(path) else ""
    if not target or "#" not in text:
        return
    import pii

    vault = pii.Vault(store=False)
    live = sorted({m.group(0) for m in pii.TOKEN_RE.finditer(text) if vault.value_for(m.group(0)) is not None})
    if live:
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                f"[pii-tokens] This writes masked token(s) {', '.join(live)} into {target}. A token stands for real "
                "personal data and is not the value itself. Approve only if the token text is what you want there."
            ),
        }})


if __name__ == "__main__":
    handlers = {"post": post, "prompt": prompt, "pre": pre}
    handlers[sys.argv[1]](json.load(sys.stdin))
