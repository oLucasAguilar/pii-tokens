"""Personal data drawn in images: OCR finds it and the token is drawn over it.

Best effort: what OCR misses passes. Needs tesseract and Pillow; without them images pass unchecked
and the hooks say so.
"""

import base64
import csv
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pii

SCALE = 3
PAD = 2
RETRY = "retry"
MAX_REREADS = 10
OCR_DIGIT_FIXES = str.maketrans("OoIlSB@", "0011580")
PASTED_IMAGE = re.compile(r"\[Image #(\d+)\]")
DOCUMENT_SHAPE = re.compile(r"\d[\dOoIl@. /-]*[\dOoIl@]")  # O, o, I, l, @: digits OCR commonly misreads


def _tesseract() -> str | None:
    # The Windows installer puts it in one of these folders, which need not be on PATH.
    folders = [os.environ.get(name, "") for name in ("ProgramFiles", "LOCALAPPDATA")]
    windows = [Path(f, sub, "Tesseract-OCR", "tesseract.exe") for f, sub in zip(folders, ("", "Programs")) if f]
    return shutil.which("tesseract") or next((str(path) for path in windows if path.is_file()), None)


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return _tesseract() is not None


def _words(png: bytes) -> list[dict]:
    out = subprocess.run([_tesseract(), "stdin", "stdout", "tsv"], input=png, capture_output=True, check=True).stdout
    rows = csv.DictReader(io.StringIO(out.decode(errors="ignore")), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [r for r in rows if (r.get("text") or "").strip()]


def _looks_like_document(text: str) -> bool:
    # A formatted CPF or CNPJ always has "-" or "/"; two numeric cells side by side ("12.345 67.890") do not.
    return bool(DOCUMENT_SHAPE.fullmatch(text)) and bool(re.search(r"[/-]", text)) and 10 <= sum(c.isdigit() for c in text) <= 15


def _tokens(text: str, vault) -> str | None:
    masked = pii.mask_text(pii.normalize_pasted_documents(text), vault)
    # A token already on screen (a screenshot of a masked chat) is not personal data.
    already = {m.group(0) for m in pii.TOKEN_RE.finditer(text)}
    tokens = [m.group(0) for m in pii.TOKEN_RE.finditer(masked) if m.group(0) not in already]
    return " ".join(tokens) if tokens else None


# The start of a CPF whose check digits OCR lost: reread it with the area to its right.
CPF_START = re.compile(r"\d{3}\.\d{3}\.\d{3}-?")


def _label(text: str, vault) -> str | None:
    text = text.strip("[]|")  # a text cursor next to the number reads as one of these
    found = _tokens(text, vault)
    if not found and CPF_START.fullmatch(text):
        return RETRY
    if found or not _looks_like_document(text):
        return found
    fixed = text.translate(OCR_DIGIT_FIXES)
    # OCR may split one document in pieces ("123. 456. 789- 09"): try it without the spaces before rereading.
    return _tokens(fixed, vault) or _tokens(re.sub(r"\s+", "", fixed), vault) or RETRY


def _reread(enlarged, group: list[dict], vault) -> str | None:
    """Second OCR pass on a document-shaped value whose check digits failed: just that crop, larger, digits only."""
    from PIL import Image

    left = min(int(w["left"]) for w in group) - 4 * PAD
    top = min(int(w["top"]) for w in group) - 4 * PAD
    right = max(int(w["left"]) + int(w["width"]) for w in group) + 4 * PAD
    bottom = max(int(w["top"]) + int(w["height"]) for w in group) + 4 * PAD
    if CPF_START.fullmatch(" ".join(w["text"] for w in group)):
        right += 4 * (bottom - top)  # room for the "-00" OCR dropped
    crop = enlarged.crop((max(left, 0), max(top, 0), min(right, enlarged.width), bottom))
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    png = io.BytesIO()
    crop.save(png, "PNG")
    text = subprocess.run(
        [_tesseract(), "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789./-"],
        input=png.getvalue(), capture_output=True, check=True,
    ).stdout.decode(errors="ignore").strip()
    return _tokens(text, vault)


def _hits(words: list[dict], vault, enlarged) -> list[tuple[tuple[int, int, int, int], str]]:
    lines: dict[tuple, list[dict]] = {}
    for w in words:
        lines.setdefault((w["block_num"], w["par_num"], w["line_num"]), []).append(w)
    hits, taken, rereads = [], set(), 0
    for line in lines.values():
        for size in (1, 2, 3, 4, 5):  # OCR splits "(11) 98765-4321" and "123.456.789 -09"; the narrowest match wins
            for i in range(len(line) - size + 1):
                group = line[i : i + size]
                ids = {id(w) for w in group}
                if ids & taken:
                    continue
                label = _label(" ".join(w["text"] for w in group), vault)
                if label == RETRY:
                    # A sheet of values shaped like ddd.ddd.ddd would otherwise reread them all and run out of time.
                    rereads += 1
                    label = _reread(enlarged, group, vault) if rereads <= MAX_REREADS else None
                if label is None:
                    continue
                taken |= ids
                left = min(int(w["left"]) for w in group) // SCALE - PAD
                top = min(int(w["top"]) for w in group) // SCALE - PAD
                right = max(int(w["left"]) + int(w["width"]) for w in group) // SCALE + PAD
                bottom = max(int(w["top"]) + int(w["height"]) for w in group) // SCALE + PAD
                hits.append(((left, top, right, bottom), label))
    return hits


def _draw(image, box: tuple[int, int, int, int], label: str) -> None:
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    font = ImageFont.load_default(size=max(10, bottom - top - 2))
    width = draw.textlength(label, font=font)
    draw.rectangle((left, top, max(right, left + width + 2 * PAD), bottom), fill="#fff3b0", outline="black")
    draw.text((left + PAD, top + 1), label, font=font, fill="black")


def _find(data: bytes, vault):
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    fmt = image.format or "PNG"
    image = image.convert("RGB")
    enlarged = image.resize((image.width * SCALE, image.height * SCALE), Image.LANCZOS)
    png = io.BytesIO()
    enlarged.save(png, "PNG")
    return image, fmt, _hits(_words(png.getvalue()), vault, enlarged)


def has_personal_data(data: bytes) -> bool:
    return bool(_find(data, pii.Vault(store=False))[2])


def _as_copy(source: bytes, size: tuple[int, int]) -> bytes:
    from PIL import Image, ImageOps

    original = ImageOps.exif_transpose(Image.open(io.BytesIO(source))).convert("RGB")
    if original.size != size:
        original = original.resize(size, Image.LANCZOS)
    out = io.BytesIO()
    original.save(out, "PNG")
    return out.getvalue()


def mask_image(data: bytes, vault, source: bytes | None = None) -> tuple[bytes, list[str]]:
    image, fmt, hits = _find(data, vault)
    if source:
        # The copy Claude Code hands the hook can read worse than the file it came from: OCR the file too,
        # at the copy's size (so it costs no more), and draw what it finds on the copy.
        try:
            from PIL import Image

            original = _as_copy(source, image.size)
            if Image.open(io.BytesIO(original)).tobytes() != image.tobytes():  # same pixels: nothing new to read
                hits += _find(original, vault)[2]
        except Exception:
            pass  # the copy's own reading still stands
    if not hits:
        return data, []
    for box, label in hits:
        _draw(image, box, label)
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue(), [label for _, label in hits]


def _slot(block: dict) -> tuple[dict, str] | None:
    """Where an image block keeps its base64: Read ("file"), Anthropic content ("source"), or MCP ("data")."""
    if block.get("type") != "image":
        return None
    for holder, key in ((block.get("file"), "base64"), (block.get("source"), "data"), (block, "data")):
        if isinstance(holder, dict) and isinstance(holder.get(key), str):
            return holder, key
    return None


def _rebuild(value, replace):
    """A copy of value with every image's base64 passed through replace(base64) -> base64."""
    if isinstance(value, list):
        return [_rebuild(v, replace) for v in value]
    if not isinstance(value, dict):
        return value
    copy = {k: _rebuild(v, replace) for k, v in value.items()}
    slot = _slot(copy)
    if slot:
        holder, key = slot
        holder[key] = replace(holder[key])
    return copy


def has_image(value) -> bool:
    found = []
    _rebuild(value, lambda data: found.append(1) or data)
    return bool(found)


def mask_images(value, vault, source: bytes | None = None) -> tuple[object, list[str]]:
    labels = []

    def mask(data: str) -> str:
        masked, found = mask_image(base64.b64decode(data), vault, source)
        labels.extend(found)
        return base64.b64encode(masked).decode() if found else data

    return _rebuild(value, mask), labels


def replace_images(value, data: str):
    return _rebuild(value, lambda _: data)


def blank_images(value, png: str):
    """Every image replaced by the given PNG, its declared media type included."""
    if isinstance(value, list):
        return [blank_images(v, png) for v in value]
    if not isinstance(value, dict):
        return value
    copy = {k: blank_images(v, png) for k, v in value.items()}
    slot = _slot(copy)
    if slot:
        holder, key = slot
        holder[key] = png
        media = {"base64": "type", "data": "media_type" if holder is not copy else "mimeType"}[key]
        holder[media] = "image/png"
    return copy


def restore_images(value, images):
    """Put back into value, in order, the image data held by images (same shape)."""
    datas = []
    _rebuild(images, lambda data: datas.append(data) or data)
    queue = iter(datas)
    return _rebuild(value, lambda _: next(queue))


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{path.name}|{stat.st_size}|{stat.st_mtime_ns}"


def _state_path(session: str) -> Path:
    return pii.DATA_DIR / "pasted-checked" / f"{session}.json"


def _pasted_state(session: str) -> dict:
    try:
        return json.loads(_state_path(session).read_text())
    except (OSError, ValueError):
        return {}


def remember_pasted(event: dict, cleared: list[Path], blocked: list[Path]) -> None:
    """Record, per session, which pasted images passed and which were blocked (and so still block)."""
    session = event.get("session_id")
    if not session or not (cleared or blocked):
        return
    state = _pasted_state(session)
    for paths, status in ((cleared, "ok"), (blocked, "blocked")):
        for path in paths:
            if path.is_file():
                state[_fingerprint(path)] = status
    target = _state_path(session)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_text(json.dumps(state))


def pasted_images(event: dict) -> list[Path]:
    """The files Claude Code saved for the images pasted into this prompt."""
    numbers = PASTED_IMAGE.findall(event.get("prompt", ""))
    transcript, session = event.get("transcript_path"), event.get("session_id")
    if not transcript or not session:
        return []
    # Windows has no user id: Claude Code keeps them in %TEMP%\\claude there.
    user_folder = f"claude-{os.getuid()}" if hasattr(os, "getuid") else "claude"
    folder = Path(tempfile.gettempdir()) / user_folder / Path(transcript).parent.name / session / "images"
    if not numbers:
        # Claude Desktop attaches a pasted image without the [Image #N] mark: take the ones not checked before.
        # A blocked one is not sent again unless pasted again, which makes a new file, so it blocks once.
        if not folder.is_dir():
            return []
        state = _pasted_state(session)
        return sorted(p for p in folder.iterdir() if p.is_file() and _fingerprint(p) not in state)
    # A pasted image whose file is not found cannot be checked; its missing path makes the check fail, and block.
    return [next(iter(sorted(folder.glob(f"{n}.*"))), folder / f"{n}.missing") for n in dict.fromkeys(numbers)]
