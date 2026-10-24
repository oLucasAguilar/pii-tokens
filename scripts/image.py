"""Personal data drawn in images: OCR finds it and the token is drawn over it.

Best effort: what OCR misses passes. Needs tesseract on PATH and Pillow; without them images pass unchecked
and the hooks say so.
"""

import base64
import csv
import io
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
OCR_DIGIT_FIXES = str.maketrans("OoIlSB", "001158")
PASTED_IMAGE = re.compile(r"\[Image #(\d+)\]")
DOCUMENT_SHAPE = re.compile(r"\d[\dOoIl. /-]*[\dOoIl]")  # O, o, I, l: digits OCR commonly misreads


def available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def _words(png: bytes) -> list[dict]:
    out = subprocess.run(["tesseract", "stdin", "stdout", "tsv"], input=png, capture_output=True, check=True).stdout
    rows = csv.DictReader(io.StringIO(out.decode(errors="ignore")), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [r for r in rows if (r.get("text") or "").strip()]


def _looks_like_document(text: str) -> bool:
    # A formatted CPF or CNPJ always has "-" or "/"; two numeric cells side by side ("12.345 67.890") do not.
    return bool(DOCUMENT_SHAPE.fullmatch(text)) and bool(re.search(r"[/-]", text)) and 10 <= sum(c.isdigit() for c in text) <= 15


def _tokens(text: str, vault) -> str | None:
    masked = pii.mask_text(pii.normalize_pasted_documents(text), vault)
    tokens = [m.group(0) for m in pii.TOKEN_RE.finditer(masked)]
    return " ".join(tokens) if tokens else None


def _label(text: str, vault) -> str | None:
    found = _tokens(text, vault)
    if found or not _looks_like_document(text):
        return found
    return _tokens(text.translate(OCR_DIGIT_FIXES), vault) or RETRY


def _reread(enlarged, group: list[dict], vault) -> str | None:
    """Second OCR pass on a document-shaped value whose check digits failed: just that crop, larger, digits only."""
    from PIL import Image

    left = min(int(w["left"]) for w in group) - 4 * PAD
    top = min(int(w["top"]) for w in group) - 4 * PAD
    right = max(int(w["left"]) + int(w["width"]) for w in group) + 4 * PAD
    bottom = max(int(w["top"]) + int(w["height"]) for w in group) + 4 * PAD
    crop = enlarged.crop((max(left, 0), max(top, 0), right, bottom))
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    png = io.BytesIO()
    crop.save(png, "PNG")
    text = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789./-"],
        input=png.getvalue(), capture_output=True, check=True,
    ).stdout.decode(errors="ignore").strip()
    return _tokens(text, vault)


def _hits(words: list[dict], vault, enlarged) -> list[tuple[tuple[int, int, int, int], str]]:
    lines: dict[tuple, list[dict]] = {}
    for w in words:
        lines.setdefault((w["block_num"], w["par_num"], w["line_num"]), []).append(w)
    hits, taken = [], set()
    for line in lines.values():
        for size in (1, 2, 3):  # OCR splits "(11) 98765-4321" and "123.456.789 -09"; the narrowest match wins
            for i in range(len(line) - size + 1):
                group = line[i : i + size]
                ids = {id(w) for w in group}
                if ids & taken:
                    continue
                label = _label(" ".join(w["text"] for w in group), vault)
                if label == RETRY:
                    label = _reread(enlarged, group, vault)
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


def mask_image(data: bytes, vault) -> tuple[bytes, list[str]]:
    image, fmt, hits = _find(data, vault)
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


def mask_images(value, vault) -> tuple[object, list[str]]:
    labels = []

    def mask(data: str) -> str:
        masked, found = mask_image(base64.b64decode(data), vault)
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


def pasted_images(event: dict) -> list[Path]:
    """The files Claude Code saved for the images pasted into this prompt."""
    numbers = PASTED_IMAGE.findall(event.get("prompt", ""))
    transcript, session = event.get("transcript_path"), event.get("session_id")
    if not numbers or not transcript or not session:
        return []
    folder = Path(tempfile.gettempdir()) / f"claude-{os.getuid()}" / Path(transcript).parent.name / session / "images"
    return [path for n in dict.fromkeys(numbers) for path in sorted(folder.glob(f"{n}.*"))[:1]]
