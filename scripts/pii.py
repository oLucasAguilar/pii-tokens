"""Mask personal data before it reaches the model.

Replaces CPF, CNPJ, email, phone and personal table columns with deterministic
tokens (`CPF#a3f9c1d2e4b5`). The real value lives in an encrypted local vault,
with the keys in the OS keyring, and only comes back through pii-unmask,
pii-reveal and pii-exec.
"""

import base64
import csv
import fcntl
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "pii-tokens" / "config.json"
BUILTIN_ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "users.noreply.github.com", "noreply.github.com")
TOKEN_SIZES = (12, 16, 24)


def _file_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _parse_list(raw: str) -> tuple:
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return tuple(str(v).strip() for v in value if str(v).strip())
    except ValueError:
        pass
    return tuple(part.strip() for part in re.split(r"[,\n]", raw) if part.strip())


def _option(key: str, default):
    from_plugin = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}")
    if from_plugin is not None:
        if isinstance(default, bool):
            return from_plugin.strip().lower() in ("1", "true", "yes", "on")
        return _parse_list(from_plugin) if isinstance(default, tuple) else from_plugin
    from_file = _file_config().get(key)
    if from_file is None:
        return default
    return tuple(from_file) if isinstance(default, tuple) else from_file


DATA_DIR = Path(_option("data_dir", str(Path.home() / ".local/share/pii-tokens"))).expanduser()
VAULT_PATH = DATA_DIR / "vault.db"
REVEAL_DIR = Path.home() / ".cache/pii-tokens/reveal"
KEYRING_SERVICE = _option("keyring_service", "pii-tokens")
ALLOWED_EMAIL_DOMAINS = BUILTIN_ALLOWED_EMAIL_DOMAINS + tuple(d.lower() for d in _option("allowed_email_domains", ()))
TABLE_TOOLS = _option("table_tools", ())
ALLOWED_TOKENS = frozenset(_option("allowed_tokens", ()))
DEV_TOOL_NAMES = _option("dev_tool_names", False)
COPY_READ_REQUEST = _option("copy_read_request", True)

TOKEN_RE = re.compile(
    r"\b(CPF|CNPJ|EMAIL|PHONE|NAME|CONTACT|DOC|TEL|NOME|CONTATO)#"
    r"([0-9a-f]{24}|[0-9a-f]{16}|[0-9a-f]{12}|[0-9a-f]{8}|\?{8})(?![0-9a-f])"
)

CPF_FORMATTED = re.compile(r"(?<![\w.])\d{3}[. ]?\d{3}[. ]?\d{3}[-. ]?\d{2}(?![\w-])")
CNPJ_FORMATTED = re.compile(r"(?<![\w.])\d{2}[. ]?\d{3}[. ]?\d{3}[/ ]?\d{4}[-. ]?\d{2}(?![\w-])")
DIGITS_11 = re.compile(r"(?<![0-9A-Za-z])\d{11}(?![0-9A-Za-z])")
DIGITS_14 = re.compile(r"(?<![0-9A-Za-z])\d{14}(?![0-9A-Za-z])")
ALNUM_CNPJ_FORMATTED = re.compile(r"(?<![\w.])[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}(?![\w-])")
ALNUM_CNPJ_PLAIN = re.compile(r"(?<![0-9A-Za-z])[0-9A-Z]{12}\d{2}(?![0-9A-Za-z])")
PHONE_BARE_AREA_CODE = re.compile(r"(?<![\w])(\d{2}) 9\d{4}-\d{4}(?!\d)")
AREA_CODES = frozenset(
    "11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 51 53 54 55 "
    "61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99".split()
)
PHONE_RE = re.compile(r"(?<![\w])(?:\+55\s?)?\(\d{2}\)\s?9?\d{4}-?\d{4}(?!\d)|(?<![\w])\+55\s?\d{2}\s?9?\d{4}-?\d{4}(?!\d)")
EMAIL_RE = re.compile(r"(?<![\w.+-])([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)")
SSH_USERS = ("git",)

NOT_PERSONAL_COLUMN = re.compile(
    r"file|arquivo|field|model|resource|class|service|group|notary|banco|bank|bordero"
    r"|(^|_)type$|numero_documento|num_documento|document_number|cidade|(^|_)uf$|pais|site$"
    r"|(^|_)(column|table|schema|index|constraint|job|queue|event|nsp)_?name$"
)
NAME_SUFFIX_COLUMN = re.compile(r"(name|nome|razao_social)$")
CONTACT_COLUMN = re.compile(
    r"e_?mail|phone|telefone|telephone|celular|mobile|whatsapp|address|endereco|street"
    r"|logradouro|bairro|complemento|zip|(^|_)cep(_|$)|(^|_)contato$"
)
DOCUMENT_COLUMN = re.compile(r"cpf|cnpj|document")
NAME_COLUMN = re.compile(
    r"(^|_)(name|nome|razao_social|fantasia|fantasy_name|trading_name|trade_name|legal_name"
    r"|social_name|sacado|cedente|cliente|responsavel|solicitante|empresa)(_|$)"
    r"|(^|_)(responsible|representative|socios?|partner|customer|owner|holder|titular|beneficiario"
    r"|devedor|pagador|sacador|avalista|fiador)$"
    r"|(^|_)(person|people|pessoas?)\d*$"
)
UNALIASED_SQL_COLUMN = re.compile(
    r"^(column|upper|lower|initcap|trim|btrim|ltrim|rtrim|coalesce|concat|concat_ws|string_agg|array_agg"
    r"|json_agg|jsonb_agg|substring|substr|left|right|replace|regexp_replace|unaccent|split_part|max|min|format)$"
)
LETTER = re.compile(r"[^\W\d_]")

# Name fields that a developer tool defines as identifiers, not people. A field is only left alone when the
# document has the tool's keys, the field sits at the tool's path AND the value fits the tool's own grammar.
_DNS = r"[a-z0-9]([a-z0-9.\-]*[a-z0-9])?"
_NPM = r"(@[a-z0-9~][a-z0-9._~\-]*/)?[a-z0-9~][a-z0-9._~\-]*"
_REPO = r"[A-Za-z0-9_.\-]+"
_K8S_NAME = r"metadata\.name|(.*\.)?(containers|initContainers|volumes|ports|env|volumeMounts)\[\]\.name"
_OPENAPI_PARAM = (r"paths\..+\.parameters\[\]\.name", r"[A-Za-z0-9_.\-\[\]]+")
_GH_RELATED = r"(owner|organization|parent|source|template_repository)"
TOOL_NAME_FIELDS = tuple(
    (frozenset(keys), re.compile(path), re.compile(shape))
    for keys, path, shape in (
        (("apiVersion", "kind", "metadata"), _K8S_NAME, r"[A-Za-z0-9_]([A-Za-z0-9_.\-]*[A-Za-z0-9_])?"),
        (("name", "dependencies"), r"name", _NPM),
        (("name", "devDependencies"), r"name", _NPM),
        (("name", "scripts"), r"name", _NPM),
        (("name", "packageManager"), r"name", _NPM),
        (("name", "workspaces"), r"name", _NPM),
        (("name", "require"), r"name", r"[a-z0-9]([_.\-]?[a-z0-9]+)*/[a-z0-9]([_.\-]?[a-z0-9]+)*"),
        (("lockfileVersion", "packages"), r"name|packages\..*\.name", _NPM),
        (("lockfileVersion", "dependencies"), r"name|dependencies\..*\.name", _NPM),
        (("Id", "Config"), r"Name", r"/[A-Za-z0-9][A-Za-z0-9_.\-]*"),
        (("Id", "Config"), r"Config\.Hostname", _DNS),
        (("terraform_version", "resources"), r"resources\[\]\.name", r"[A-Za-z_][A-Za-z0-9_\-]*"),
        (("openapi", "paths"), *_OPENAPI_PARAM),
        (("swagger", "paths"), *_OPENAPI_PARAM),
        (("full_name", "owner", "default_branch"), rf"name|{_GH_RELATED}\.name", _REPO),
        (("full_name", "owner", "default_branch"), rf"full_name|{_GH_RELATED}\.full_name", rf"{_REPO}/{_REPO}"),
    )
)
TERMINAL_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\r(?!\n)")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def valid_cpf(value: str) -> bool:
    d = [int(c) for c in _digits(value)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for size in (9, 10):
        total = sum(d[i] * (size + 1 - i) for i in range(size))
        if (total * 10) % 11 % 10 != d[size]:
            return False
    return True


def valid_cnpj(value: str) -> bool:
    d = [int(c) for c in _digits(value)]
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum(d[i] * weights[i] for i in range(size))
        rest = total % 11
        if (0 if rest < 2 else 11 - rest) != d[size]:
            return False
    return True


def _alnum(value: str) -> str:
    return re.sub(r"[./-]", "", value).upper()


def valid_alnum_cnpj(value: str) -> bool:
    raw = _alnum(value)
    if len(raw) != 14 or raw.isdigit() or not raw.isalnum() or not raw.isascii() or not raw[12:].isdigit():
        return False
    d = [ord(c) - 48 for c in raw]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        rest = sum(d[i] * weights[i] for i in range(size)) % 11
        if (0 if rest < 2 else 11 - rest) != d[size]:
            return False
    return True


def _document(value: str) -> str:
    return _alnum(value) if valid_alnum_cnpj(value) else _digits(value)


def _looks_like_timestamp(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y%m%d%H%M%S")
        return value.startswith(("19", "20"))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Keys and vault
# ---------------------------------------------------------------------------

class Vault:
    def __init__(self, store: bool = True):
        self.store = store
        self.hmac_key = None
        self.fernet = None
        self._db = None
        try:
            self._load_keys()
        except Exception as e:
            print(f"[pii-tokens] keyring unavailable, tokens cannot be reversed: {e}", file=sys.stderr)

    def _load_keys(self):
        import keyring
        from cryptography.fernet import Fernet

        DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(DATA_DIR / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            hmac_key = keyring.get_password(KEYRING_SERVICE, "hmac")
            vault_key = keyring.get_password(KEYRING_SERVICE, "vault")
            if not hmac_key or not vault_key:
                hmac_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
                vault_key = Fernet.generate_key().decode()
                keyring.set_password(KEYRING_SERVICE, "hmac", hmac_key)
                keyring.set_password(KEYRING_SERVICE, "vault", vault_key)
        self.hmac_key = hmac_key.encode()
        self.fernet = Fernet(vault_key.encode())

    @property
    def db(self):
        if self._db is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            fresh = not VAULT_PATH.exists()
            self._db = sqlite3.connect(VAULT_PATH, timeout=10)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, value BLOB NOT NULL)"
            )
            if fresh:
                os.chmod(VAULT_PATH, 0o600)
        return self._db

    def _digest(self, kind: str, value: str) -> str:
        normalized = _document(value) if kind in ("CPF", "CNPJ") else value.strip().lower()
        return hmac.new(self.hmac_key, f"{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()

    def is_allowed(self, kind: str, value: str) -> bool:
        if self.hmac_key is None or not ALLOWED_TOKENS:
            return False
        digest = self._digest(kind, value)
        return any(f"{kind}#{digest[:size]}" in ALLOWED_TOKENS for size in TOKEN_SIZES)

    def mask(self, kind: str, value: str) -> str:
        return value if self.is_allowed(kind, value) else self.token_for(kind, value)

    def token_for(self, kind: str, value: str) -> str:
        if self.hmac_key is None:
            return f"{kind}#????????"
        normalized = _document(value) if kind in ("CPF", "CNPJ") else value.strip().lower()
        digest = self._digest(kind, value)
        stored = normalized if kind in ("CPF", "CNPJ") else value.strip()
        for size in TOKEN_SIZES:
            token = f"{kind}#{digest[:size]}"
            if not self.store:
                return token
            existing = self.value_for(token)
            if existing is None:
                self.db.execute(
                    "INSERT INTO tokens (token, value) VALUES (?, ?)",
                    (token, self.fernet.encrypt(stored.encode())),
                )
                self.db.commit()
                return token
            if existing == stored:
                return token
        raise RuntimeError(f"token collision at every size for {kind}")

    def value_for(self, token: str) -> str | None:
        if self.fernet is None or not VAULT_PATH.exists():
            return None
        row = self.db.execute("SELECT value FROM tokens WHERE token = ?", (token,)).fetchone()
        return self.fernet.decrypt(row[0]).decode() if row else None


# ---------------------------------------------------------------------------
# Mask and unmask text
# ---------------------------------------------------------------------------

def is_personal_email(match: re.Match) -> bool:
    user, domain = match.group(1).lower(), match.group(2).lower()
    return user not in SSH_USERS and not any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS)


IPV4_LIKE = re.compile(r"(\d{3})\.(\d{3})\.(\d{3})\.\d{2}")


def looks_like_ipv4(value: str) -> bool:
    m = IPV4_LIKE.fullmatch(value)
    return bool(m) and all(int(octet) <= 255 for octet in m.groups())


PASTE_SPACES = "\u00a0\u2007\u202f"
PASTE_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
PASTE_INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff"
PASTE_CHARS = re.compile(f"[{PASTE_SPACES}{PASTE_DASHES}{PASTE_INVISIBLE}]")


def normalize_pasted_documents(text: str) -> str:
    """Rewrite a document pasted from PDF, Word or the web (odd spaces, hyphens, invisible
    characters) to its plain form, and only when it is a valid one; the rest is untouched."""
    if not PASTE_CHARS.search(text):
        return text
    kept, origin = [], []
    for i, ch in enumerate(text):
        if ch in PASTE_INVISIBLE:
            continue
        kept.append(" " if ch in PASTE_SPACES else "-" if ch in PASTE_DASHES else ch)
        origin.append(i)
    plain = "".join(kept)
    checks = (
        (CNPJ_FORMATTED, valid_cnpj),
        (CPF_FORMATTED, lambda v: valid_cpf(v) and not looks_like_ipv4(v)),
        (PHONE_RE, lambda v: True),
    )
    spans = []
    for pattern, valid in checks:
        for m in pattern.finditer(plain):
            start, end = origin[m.start()], origin[m.end() - 1] + 1
            if text[start:end] != m.group(0) and valid(m.group(0)):
                spans.append((start, end, m.group(0)))
    for start, end, value in sorted(spans, reverse=True):
        if not any(s < end and start < e for s, e, _ in spans if (s, e) != (start, end)):
            text = text[:start] + value + text[end:]
    return text


def mask_text(text: str, vault: Vault) -> str:
    text = normalize_pasted_documents(TERMINAL_ESCAPE.sub("", text))

    def cpf(m):
        value = m.group(0)
        return vault.mask("CPF", value) if valid_cpf(value) and not looks_like_ipv4(value) else value

    def cnpj(m):
        value = m.group(0)
        if valid_cnpj(value) and not _looks_like_timestamp(value):
            return vault.mask("CNPJ", value)
        return value

    def email(m):
        if not is_personal_email(m):
            return m.group(0)
        return vault.mask("EMAIL", m.group(0))

    def alnum_cnpj(m):
        return vault.mask("CNPJ", m.group(0)) if valid_alnum_cnpj(m.group(0)) else m.group(0)

    def bare_phone(m):
        return vault.mask("PHONE", m.group(0)) if m.group(1) in AREA_CODES else m.group(0)

    text = ALNUM_CNPJ_FORMATTED.sub(alnum_cnpj, text)
    text = ALNUM_CNPJ_PLAIN.sub(alnum_cnpj, text)
    text = CNPJ_FORMATTED.sub(cnpj, text)
    text = CPF_FORMATTED.sub(cpf, text)
    text = DIGITS_14.sub(cnpj, text)
    text = DIGITS_11.sub(cpf, text)
    text = PHONE_RE.sub(lambda m: vault.mask("PHONE", m.group(0)), text)
    text = PHONE_BARE_AREA_CODE.sub(bare_phone, text)
    return EMAIL_RE.sub(email, text)


def unmask_text(text: str, vault: Vault) -> str:
    def replace(m):
        return vault.value_for(m.group(0)) or m.group(0)

    for _ in range(3):
        unmasked = TOKEN_RE.sub(replace, text)
        if unmasked == text:
            break
        text = unmasked
    return text


def mask_json(value, vault: Vault, tables: bool = False, tool: str = ""):
    if isinstance(value, str):
        return mask_text(mask_json_text(mask_table_text(value, vault) if tables else value, vault, tool), vault)
    if isinstance(value, list):
        return [mask_json(v, vault, tables, tool) for v in value]
    if isinstance(value, dict):
        return {k: mask_json(v, vault, tables, tool) for k, v in value.items()}
    return value


def _path_pattern(glob: str) -> re.Pattern:
    escaped = re.escape(glob)
    if escaped.startswith(r"\*\*\."):
        escaped = r"(?:.*\.)?" + escaped[len(r"\*\*\.") :]
    return re.compile(escaped.replace(r"\*\*", ".*").replace(r"\*", r"[^.]*"))


_FIELD_FILTER = re.compile(r"(.*)\[([^\]=]+)=([^\]]*)\](\.[^.\[\]]+)")


def parse_field_rules(rules) -> tuple:
    """Rules look like "mcp__monday__:**.items[].name": a tool name prefix, then a field path.

    "[key=value]" before the last field keeps only objects where that key holds that value,
    as in "**.column_values[type=people].text".
    """
    parsed = []
    for rule in rules:
        tool, sep, path = str(rule).partition(":")
        tool, path = tool.strip().rstrip("*"), path.strip()
        if not (sep and tool and path):
            continue
        only = None
        found = _FIELD_FILTER.fullmatch(path)
        if found:
            path, only = f"{found[1]}[]{found[4]}", (found[2].strip(), found[3].strip())
        parsed.append((tool, _path_pattern(path), only))
    return tuple(parsed)


READABLE_FIELDS = parse_field_rules(_option("readable_fields", ()))
MASKED_FIELDS = parse_field_rules(_option("masked_fields", ()))


def _field_rules(tool: str) -> tuple:
    """(readable, masked) rules for this tool, each as (path pattern, key filter)."""
    pick = lambda rules: tuple((path, only) for prefix, path, only in rules if tool.startswith(prefix)) if tool else ()
    return pick(READABLE_FIELDS), pick(MASKED_FIELDS)


def _hits(rules: tuple, path: str, holder: dict) -> bool:
    return any(
        pattern.fullmatch(path) and (only is None or str(holder.get(only[0])) == only[1]) for pattern, only in rules
    )


def is_tool_name_field(document, path: str, value: str) -> bool:
    return isinstance(document, dict) and any(
        keys <= document.keys() and where.fullmatch(path) and shape.fullmatch(value)
        for keys, where, shape in TOOL_NAME_FIELDS
    )


def _is_people_text(column: dict, key, item) -> bool:
    # Monday returns a people column as {"type": "people", "text": "Name One, Name Two"}.
    return key == "text" and column.get("type") == "people" and isinstance(item, str) and bool(item.strip())


def _mask_by_key(value, vault: Vault, document=None, path: str = "", rules: tuple = ((), ())):
    readable, forced = rules
    if isinstance(value, list):
        if document is None:
            return [_mask_by_key(v, vault, v, "", rules) for v in value]
        return [_mask_by_key(v, vault, document, f"{path}[]", rules) for v in value]
    if isinstance(value, dict):
        document = value if document is None else document
        masked = {}
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            kind = column_kind(str(key))
            if forced and isinstance(item, (str, int)) and not isinstance(item, bool) and _hits(forced, here, value):
                masked[key] = mask_cell("NAME", str(item), vault) if str(item).strip() else item
            elif kind and isinstance(item, (str, int)) and not isinstance(item, bool) and str(item):
                if DEV_TOOL_NAMES and kind == "NAME" and is_tool_name_field(document, here, str(item)):
                    masked[key] = item
                    continue
                if _hits(readable, here, value):
                    masked[key] = item
                    continue
                cell = mask_cell(kind, str(item), vault)
                masked[key] = item if cell == str(item) else cell
            elif _is_people_text(value, key, item) and not _hits(readable, here, value):
                masked[key] = ", ".join(mask_cell("NAME", person.strip(), vault) for person in item.split(","))
            else:
                masked[key] = _mask_by_key(item, vault, document, here, rules)
        return masked
    return value


def mask_json_text(text: str, vault: Vault, tool: str = "") -> str:
    """Mask by key name when the whole text is a JSON document."""
    rules = _field_rules(tool)
    if text.lstrip().startswith(("{", "[")):
        try:
            document = json.loads(text)
        except ValueError:
            pass
        else:
            masked = _mask_by_key(document, vault, rules=rules)
            if masked == document:
                return text
            return json.dumps(masked, ensure_ascii=False, indent=2 if "\n" in text.strip() else None)
    return _mask_embedded_json(text, vault, rules)


# Only where the next character can open a JSON value: every failed attempt costs a scan of the text.
_JSON_OPENING = r"(?=\{\s*[\"}]|\[\s*[\[{\"\d\-tfn\]])"
EMBEDDED_JSON_START = re.compile(rf"(?m)^[ \t]*{_JSON_OPENING}|: {_JSON_OPENING}")
_DECODER = json.JSONDecoder()


def _decode_at(text: str, start: int):
    """Try the line first; the rest of the text only when the line ends mid-document."""
    line_end = text.find("\n", start)
    line = text[start:] if line_end < 0 else text[start:line_end]
    try:
        document, end = _DECODER.raw_decode(line)
        return document, start + end
    except json.JSONDecodeError as error:
        if line_end < 0 or error.pos < len(line):
            return None
    except RecursionError:
        return None
    try:
        return _DECODER.raw_decode(text, start)
    except (ValueError, RecursionError):
        return None


def _mask_embedded_json(text: str, vault: Vault, rules: tuple) -> str:
    """JSON that starts a line or follows "label: ", as in logs, NDJSON and code blocks."""
    parts, cursor = [], 0
    for match in EMBEDDED_JSON_START.finditer(text):
        start = match.end()
        if start < cursor:
            continue
        decoded = _decode_at(text, start)
        if decoded is None:
            continue
        document, end = decoded
        if not isinstance(document, (dict, list)):
            continue
        masked = _mask_by_key(document, vault, rules=rules)
        if masked != document:
            snippet = text[start:end]
            parts += [text[cursor:start], json.dumps(masked, ensure_ascii=False, indent=2 if "\n" in snippet else None)]
            cursor = end
    return "".join(parts) + text[cursor:] if parts else text


def _normalize_header(column: str) -> str:
    plain = unicodedata.normalize("NFKD", column).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain.strip().lower()).strip("_")


def column_kind(column: str) -> str | None:
    name = _normalize_header(column)
    if not name or NOT_PERSONAL_COLUMN.search(name):
        return None
    if UNALIASED_SQL_COLUMN.search(name):
        return "NAME"
    if NAME_SUFFIX_COLUMN.search(name):
        return "NAME"
    if CONTACT_COLUMN.search(name):
        return "CONTACT"
    if DOCUMENT_COLUMN.search(name):
        return "DOC"
    if NAME_COLUMN.search(name):
        return "NAME"
    return None


def mask_cell(kind: str, value: str, vault: Vault) -> str:
    if value in ("", "NULL") or TOKEN_RE.fullmatch(value):
        return value
    masked = mask_text(value, vault)
    if masked != value:
        return masked
    if kind == "NAME" and not LETTER.search(value):
        return value
    if kind == "DOC":
        digits = _digits(value)
        if len(digits) < 8:
            return value
        if len(digits) in (9, 10) and valid_cpf(digits.zfill(11)):
            return value if vault.is_allowed("CPF", digits.zfill(11)) else vault.token_for("CPF", digits.zfill(11))
        if len(digits) in (12, 13) and valid_cnpj(digits.zfill(14)):
            return value if vault.is_allowed("CNPJ", digits.zfill(14)) else vault.token_for("CNPJ", digits.zfill(14))
    return vault.mask(kind, value)


def render_table(columns: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(c) for c in columns]
    for row in rows:
        for i, v in enumerate(row[: len(widths)]):
            widths[i] = max(widths[i], len(v))

    def fmt(values):
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(values[: len(widths)]))

    return [fmt(columns), "-+-".join("-" * w for w in widths), *[fmt(r) for r in rows]]


def mask_table_text(text: str, vault: Vault) -> str:
    """Mask by column name a psql-style table (`a | b` header, `--+--` rule)."""
    lines = text.split("\n")
    for header_at in range(min(3, len(lines) - 1)):
        if lines[header_at].strip() and re.fullmatch(r"-+(-\+-+)*", lines[header_at + 1]):
            break
    else:
        return text

    columns = [c.strip() for c in lines[header_at].split(" | ")]
    kinds = [column_kind(c) for c in columns]
    if not any(kinds):
        return text

    body_end = header_at + 2
    while body_end < len(lines) and lines[body_end].strip() and not lines[body_end].startswith("("):
        body_end += 1
    rows = []
    for line in lines[header_at + 2 : body_end]:
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) != len(columns):
            return text
        rows.append([mask_cell(k, v, vault) if k else v for k, v in zip(kinds, cells)])

    return "\n".join(lines[:header_at] + render_table(columns, rows) + lines[body_end:])


def mask_rows(rows: list[list[str]], vault: Vault) -> list[list[str]]:
    """The first row is the header; personal columns are masked by name."""
    if not rows:
        return rows
    kinds = [column_kind(str(c)) for c in rows[0]]
    masked = [rows[0]]
    for row in rows[1:]:
        masked.append([
            mask_cell(kinds[i], str(v), vault) if i < len(kinds) and kinds[i] and v not in (None, "") else v
            for i, v in enumerate(row)
        ])
    return masked


def mask_csv_text(text: str, vault: Vault) -> str:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    out = io.StringIO()
    csv.writer(out, dialect, lineterminator="\n").writerows(mask_rows(rows, vault))
    return out.getvalue()
