#!/usr/bin/env python3
"""Masking tests. Every document is generated at runtime, so this file holds no real CPF/CNPJ.

The one literal is the alphanumeric CNPJ example published by Receita Federal, kept as a known answer.

Runs against a throwaway vault and config: python3 tests/test_pii.py
"""

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
# resolve(): on macOS the temp dir is under /var, a link to /private/var, which breaks relative links.
SANDBOX = Path(tempfile.mkdtemp(prefix="pii-tokens-test-")).resolve()
(SANDBOX / "pii-tokens").mkdir()
(SANDBOX / "pii-tokens" / "config.json").write_text(json.dumps({
    "data_dir": str(SANDBOX / "data"),
    "keyring_service": "pii-tokens-test",
    "allowed_email_domains": ["acme.example"],
    "table_tools": ["mcp__db__"],
}))
os.environ["XDG_CONFIG_HOME"] = str(SANDBOX)
for key in [k for k in os.environ if k.startswith("CLAUDE_PLUGIN_OPTION_")]:
    del os.environ[key]

sys.path.insert(0, str(SCRIPTS))
import hook as hook_module  # noqa: E402
import pii  # noqa: E402

failures = 0


def check(name, condition):
    global failures
    failures += not condition
    print(("ok   " if condition else "FAIL ") + name)


def hook(mode, event):
    return subprocess.run(
        ["python3", str(SCRIPTS / "hook.py"), mode], input=json.dumps(event), capture_output=True, text=True
    ).stdout


def fake_cpf(seed, leading_zero=False):
    rng = random.Random(seed)
    while True:
        d = [rng.randint(0, 9) for _ in range(9)]
        if leading_zero:
            d[0] = 0
        for size in (9, 10):
            d.append(sum(d[i] * (size + 1 - i) for i in range(size)) * 10 % 11 % 10)
        if len(set(d)) > 1:
            return "".join(map(str, d))


def fake_cnpj(seed):
    rng = random.Random(seed)
    d = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        rest = sum(d[i] * weights[i] for i in range(size)) % 11
        d.append(0 if rest < 2 else 11 - rest)
    return "".join(map(str, d))


cpf = fake_cpf(1)
hex_string = "a" + fake_cpf(4)
cpf_formatted = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
cnpj = fake_cnpj(2)
cnpj_formatted = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
assert pii.valid_cpf(cpf) and pii.valid_cnpj(cnpj)

vault = pii.Vault()
text = pii.mask_text(
    f"a {cpf_formatted} b {cpf} c {cnpj_formatted} d {cnpj} e maria@cliente.example f dev@acme.example "
    f"g 20261005123045 h 12345678901 i {hex_string} j (11) 98765-4321 k git@github.com:org/repo.git", vault)
check("formatted and raw CPF share one token", len(set(re.findall(r"CPF#\w{12}", text))) == 1 and text.count("CPF#") == 2)
check("formatted and raw CNPJ", text.count("CNPJ#") == 2)
check("external email masked, configured domain kept", "EMAIL#" in text and "dev@acme.example" in text)
check("git SSH remote is not an email", "git@github.com:org/repo.git" in text)
check("14-digit timestamp kept", "20261005123045" in text)
check("11 digits with an invalid check digit kept", "12345678901" in text)
check("digits inside a hex string kept", hex_string in text)
check("phone masked", "PHONE#" in text)
colored = f"doc {cpf[:3]}\x1b[01;31m\x1b[K{cpf[3:7]}\x1b[m\x1b[K{cpf[7:]}"
check("CPF split by grep --color is masked", cpf not in re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", pii.mask_text(colored, vault)) and "CPF#" in pii.mask_text(colored, vault))
check("progress bar carriage return does not split a CPF", "CPF#" in pii.mask_text(f"{cpf[:5]}\r{cpf[5:]}", vault))
check("round trip", cpf in pii.unmask_text(text, vault) and "maria@cliente.example" in pii.unmask_text(text, vault))

# Documents pasted from PDF, Word or a web page carry a no-break space, a Unicode hyphen or a zero-width space.
pasted = {
    "no-break space": f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}\u00a0{cpf[9:]}",
    "Unicode hyphen": f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}\u2010{cpf[9:]}",
    "minus sign": f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}\u2212{cpf[9:]}",
    "zero-width space": f"{cpf[:3]}\u200b.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}",
    "narrow no-break spaces": f"{cpf[:3]}\u202f{cpf[3:6]}\u202f{cpf[6:9]}\u202f{cpf[9:]}",
}
for label, value in pasted.items():
    check(f"CPF with a {label} is masked", "CPF#" in pii.mask_text(f"doc {value} ok", vault))
check("pasted CPF gets the same token as the plain one",
      pii.mask_text(pasted["Unicode hyphen"], vault) == pii.mask_text(cpf_formatted, vault))
check("CNPJ with a Unicode hyphen is masked", "CNPJ#" in pii.mask_text(cnpj_formatted.replace("-", "\u2011"), vault))
check("phone with a no-break space is masked", "PHONE#" in pii.mask_text("ligar (11)\u00a098765\u20104321", vault))
check("a prompt with a pasted CPF is blocked", "block" in hook("prompt", {"prompt": f"cpf {pasted['no-break space']}"}))
check("a number range with an en dash is kept", pii.mask_text("pages 10\u201320 and 2019\u20132024", vault) == "pages 10\u201320 and 2019\u20132024")
family = "\U0001F468\u200d\U0001F469\u200d\U0001F467"
check("an emoji joined by zero-width joiners is kept", pii.mask_text(f"hi {family} 123", vault) == f"hi {family} 123")

# An IPv4 address shaped ddd.ddd.ddd.dd can carry valid CPF check digits; octets above 255 cannot be an IP.
ip_like = next(f"{a}.{b}.{c}.{d:02d}" for a in range(100, 256) for b in range(100, 256) for c in range(100, 256)
               for d in range(100) if pii.valid_cpf(f"{a}{b}{c}{d:02d}"))
check("an IP with CPF check digits is kept", pii.mask_text(f"host {ip_like} up", vault) == f"host {ip_like} up")
check("an IP with CPF check digits does not block the prompt", hook("prompt", {"prompt": f"ping {ip_like}"}) == "")
big = next(f"{a}.{b}.{c}.{d:02d}" for a in range(256, 1000) for b in range(100, 1000) for c in range(100, 1000)
           for d in range(100) if pii.valid_cpf(f"{a}{b}{c}{d:02d}"))
check("dotted CPF with a block above 255 is masked", "CPF#" in pii.mask_text(f"doc {big}", vault))

# Everyday values that are not personal data must come back unchanged (measured 22/10: 0 of 500 each).
untouched = [
    "3f2b8c1e-9a4d-4e7b-8c2f-1d6a5b9e0c73", hashlib.sha256(b"pii").hexdigest(), "a1b2c3d", "2026-10-22T10:30:00Z",
    "R$ 1.234.567,89", "1761134400000", "4815162342", "23793381286000012345678901234567890123456789",
    "3526 1012 3456 7800 0123 5500 1000 0012 3410 0012 3456", "10.0.0.1", "v12.4.130",
]
for value in untouched:
    check(f"not personal data, kept: {value[:24]}", pii.mask_text(f"x {value} y", vault) == f"x {value} y"
          and pii.mask_json(json.dumps({"id": value}), vault) == json.dumps({"id": value}))

alnum_cnpj_formatted = "12.ABC.345/01DE-35"
alnum_cnpj = "12ABC34501DE35"
check("alphanumeric CNPJ, formatted and raw, 1 token",
      pii.mask_text(alnum_cnpj_formatted, vault) == pii.mask_text(alnum_cnpj, vault) and pii.mask_text(alnum_cnpj, vault).startswith("CNPJ#"))
check("alphanumeric CNPJ round trip", pii.unmask_text(pii.mask_text(f"doc {alnum_cnpj_formatted}", vault), vault) == f"doc {alnum_cnpj}")
check("alphanumeric id with wrong check digits kept", pii.mask_text("12ABC34501DE36", vault) == "12ABC34501DE36")
check("numeric CNPJ token unchanged by the alphanumeric rule", pii.mask_text(cnpj, vault) == pii.mask_text(cnpj_formatted, vault))
check("phone with a bare area code masked", pii.mask_text("tel 11 91234-5678", vault).startswith("tel PHONE#"))
check("same shape with an invalid area code kept", pii.mask_text("lote 10 91234-5678", vault) == "lote 10 91234-5678")

cpf_variants = [cpf_formatted, cpf, f"{cpf[:3]} {cpf[3:6]} {cpf[6:9]} {cpf[9:]}", f"{cpf[:9]}-{cpf[9:]}"]
cnpj_variants = [cnpj_formatted, cnpj, f"{cnpj[:2]} {cnpj[2:5]} {cnpj[5:8]} {cnpj[8:12]} {cnpj[12:]}", f"{cnpj[:8]}/{cnpj[8:12]}-{cnpj[12:]}"]
check("CPF in 4 formats, 1 token", len({pii.mask_text(x, vault) for x in cpf_variants}) == 1)
check("CNPJ in 4 formats, 1 token", len({pii.mask_text(x, vault) for x in cnpj_variants}) == 1)
zero_cpf = fake_cpf(3, leading_zero=True)
check("CPF that lost its leading zero in Excel, in a CPF column",
      pii.mask_csv_text(f"id,CPF\n1,{zero_cpf[1:]}\n", vault).split()[-1] == "1," + pii.mask_text(zero_cpf, vault))

table = ("[production | database 6]\nid | name     | cpf | document       | trading_name\n"
         f"---+----------+-----+----------------+-------------\n1  | Jane Roe | 3   | {cpf_formatted} | Shop\n\n(1 row)")
masked = pii.mask_table_text(table, vault)
check("name column masked", "Jane" not in masked and "Shop" not in masked)
check("count in a cpf column kept", "| 3 " in masked)
check("CPF in a document column becomes CPF#", "CPF#" in masked)
check("masking twice changes nothing", pii.mask_table_text(masked, vault) == masked)
check("token has 12 hex characters", re.fullmatch(r"CPF#[0-9a-f]{12}", pii.mask_text(cpf, vault)) is not None)

nested = vault.token_for("NAME", vault.token_for("NAME", "Jane Roe"))
probe = "Collision Probe Person"
natural = pii.Vault(store=False).token_for("NAME", probe)
vault.db.execute("DELETE FROM tokens WHERE token LIKE ?", (natural + "%",))
vault.db.execute("INSERT INTO tokens (token, value) VALUES (?, ?)", (natural, vault.fernet.encrypt(b"someone else")))
vault.db.commit()
collided = vault.token_for("NAME", probe)
check("collision yields a longer token", len(collided) > len(natural) and pii.unmask_text(collided, vault) == probe)
check("an occupied token keeps its owner", pii.unmask_text(natural, vault) == "someone else")
legacy = "NOME#" + natural.split("#")[1][:8]
vault.db.execute("INSERT INTO tokens (token, value) VALUES (?, ?)", (legacy, vault.fernet.encrypt(b"old value")))
vault.db.commit()
check("legacy 8-char Portuguese token still resolves", pii.unmask_text(legacy + " end", vault) == "old value end")
check("token of a token resolves to the value", pii.unmask_text(nested, vault) == "Jane Roe")

check("accented header", pii.column_kind("Razão Social") == "NAME" and pii.column_kind("E-mail") == "CONTACT")
check("metadata is not personal", pii.column_kind("document_type") is None and pii.column_kind("filename") is None)
check("schema metadata is not a name", pii.column_kind("column_name") is None and pii.column_kind("table_name") is None)
csv_text = pii.mask_csv_text(f"id,Nome,CPF,Valor\n1,Maria Silva,{cpf},10.5\n", vault)
check("CSV by header", "Maria" not in csv_text and "CPF#" in csv_text and "10.5" in csv_text)

api = '{"id": 7, "nome": "Jane Roe", "customer": 7, "email": "x@corp.example.net", "status": "active"}'
masked_api = pii.mask_json(api, vault)
check("JSON key nome masked", "Jane" not in masked_api and "NAME#" in masked_api)
check("numeric JSON customer key kept", '"customer": 7' in masked_api)
check("JSON status kept", '"active"' in masked_api)
check("text that is not JSON is unchanged", pii.mask_json("{ not json", vault) == "{ not json")
unaliased = "id | upper | max\n---+-------+----\n1  | JANE ROE | 300\n\n(1 row)"
masked_unaliased = pii.mask_table_text(unaliased, vault)
check("unaliased SQL function masks text", "JANE" not in masked_unaliased and "| 300" in masked_unaliased)
check("customer column holding an id kept",
      pii.mask_table_text("customer | x\n---------+--\n123      | a\n\n(1 row)", vault).count("123") == 1)
check("list option parses JSON and commas", pii._parse_list('["a.com", "b.com"]') == ("a.com", "b.com")
      and pii._parse_list("a.com, b.com\nc.com") == ("a.com", "b.com", "c.com"))

bash_shape = {"stdout": "x", "stderr": "y", "interrupted": False, "isImage": False}
read_shape = {"type": "text", "file": {"filePath": "/a.csv", "content": "x", "numLines": 1}}
suppressed_bash = hook_module._suppress(bash_shape, "notice")
suppressed_read = hook_module._suppress(read_shape, "notice")
check("suppression keeps the Bash shape",
      set(suppressed_bash) == set(bash_shape) and suppressed_bash["stdout"] == "notice" and suppressed_bash["isImage"] is False)
check("suppression keeps the Read shape",
      suppressed_read["type"] == "text" and suppressed_read["file"]["content"] == "notice" and suppressed_read["file"]["numLines"] == 1)

out = hook("post", {"tool_name": "Bash", "tool_response": {"stdout": f"x {cpf_formatted}", "stderr": ""}})
check("hook masks Bash", "CPF#" in out and cpf_formatted not in out)
out = hook("post", {"tool_name": "Read", "tool_input": {"file_path": str(SCRIPTS / "pii.py")}, "tool_response": {"file": {"content": cpf}}})
check("hook skips a git-tracked file", out == "")
out = hook("post", {"tool_name": "mcp__db__query", "tool_response": [{"type": "text", "text": "name\n----\nBeltrano\n\n(1 row)"}]})
check("hook masks a column from a configured table tool", "Beltrano" not in out and "NAME#" in out)
out = hook("post", {"tool_name": "mcp__other__query", "tool_response": [{"type": "text", "text": "name\n----\nBeltrano\n\n(1 row)"}]})
check("table mode is off for tools not configured", "Beltrano" in out or out == "")
token = pii.mask_text(cpf, vault)
check("token in a query resolves to the real value", cpf in pii.unmask_text(f"where d = '{token}'", vault))
check("prompt with CPF blocked", '"block"' in hook("prompt", {"prompt": f"cpf {cpf_formatted}"}))
check("prompt with pii-ok passes", hook("prompt", {"prompt": f"pii-ok {cpf_formatted}"}) == "")
check("prompt with a formatted phone blocked", '"block"' in hook("prompt", {"prompt": "call (11) 98765-4321 today"}))
check("prompt with a phone and area code blocked", '"block"' in hook("prompt", {"prompt": "call 11 98765-4321 today"}))
check("prompt with an 11-digit ticket number passes",
      not pii.valid_cpf("12345678901") and hook("prompt", {"prompt": "ticket 12345678901 closed"}) == "")
check("prompt naming the PHONE# token passes", hook("prompt", {"prompt": "tokens look like PHONE#de9c75a6dc05"}) == "")

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "client.txt").write_text(f"doc {cpf}\n")
    (Path(tmp) / "clean.txt").write_text("nothing personal\n")
    (Path(tmp) / "partners.csv").write_text("id,Sócio\n1,Jane Roe\n")
    check("@file with CPF blocked", '"block"' in hook("prompt", {"prompt": "see @client.txt", "cwd": tmp}))
    check("@file with a name in a CSV column blocked", '"block"' in hook("prompt", {"prompt": "see @partners.csv", "cwd": tmp}))
    check("@file without PII passes", hook("prompt", {"prompt": "see @clean.txt", "cwd": tmp}) == "")
    check("an email in the prompt is not an @file", hook("prompt", {"prompt": "write to dev@acme.example", "cwd": tmp}) == "")
check("@file tracked by git passes", hook("prompt", {"prompt": f"see @{SCRIPTS / 'pii.py'}", "cwd": "/"}) == "")

package = '{"name": "my-app", "version": "1.0.0", "dependencies": {}}'
pod = '{"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "api-7d9f"}, "spec": {"containers": [{"name": "web"}]}}'
forged = [
    '{"name": "Maria Silva", "version": "1", "scripts": {}}',
    '{"Id": 9, "Config": {"Hostname": "x"}, "Name": "Maria Silva"}',
    '{"apiVersion": "v1", "kind": "Cliente", "metadata": {"name": "Maria Silva"}}',
    '{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "clientes"}, "data": {"contact_name": "Maria Silva"}}',
    '{"name": "relatorio", "version": "1", "scripts": {}, "customers": [{"name": "Maria Silva"}]}',
]
check("strict by default: a package name is masked", "my-app" not in pii.mask_json(package, vault))
pii.DEV_TOOL_NAMES = True
check("dev tool names: package and pod names are kept", pii.mask_json(package, vault) == package and pii.mask_json(pod, vault) == pod)
check("dev tool names: a person in a tool-shaped document is still masked", all("Maria Silva" not in pii.mask_json(doc, vault) for doc in forged))
check("dev tool names: a plain person record is still masked", "Maria" not in pii.mask_json('{"id": 1, "name": "Maria"}', vault))
check("dev tool names: tool names next to a masked person are kept", "clientes" in pii.mask_json(forged[3], vault) and "relatorio" in pii.mask_json(forged[4], vault))
pii.DEV_TOOL_NAMES = False

tracker = json.dumps({"data": {"boards": [{"id": "1", "name": "Dev tasks", "items_page": {"items": [
    {"id": "2", "name": "Handle return outcomes", "subitems": [{"id": "3", "name": "Write the spec"}],
     "updates": [{"id": "4", "creator": {"name": "Maria Silva"}, "text_body": "done"}]},
    {"id": "5", "name": f"Refund {cpf_formatted}"},
]}}]}})
items_page = json.dumps({"items": [{"id": "2", "name": "Handle return outcomes"}]})
tracker_rules = ("mcp__tracker__:**.items[].name", "mcp__tracker__:**.subitems[].name", "mcp__tracker__:**.boards[].name")
check("readable fields: strict by default, a task title is masked",
      "Handle return" not in pii.mask_json(tracker, vault, tool="mcp__tracker__all_api_read"))
pii.READABLE_FIELDS = pii.parse_field_rules(tracker_rules)
readable = pii.mask_json(tracker, vault, tool="mcp__tracker__all_api_read")
check("readable fields: board, item and subitem titles are kept",
      all(t in readable for t in ("Dev tasks", "Handle return outcomes", "Write the spec")))
check("readable fields: the path matches at any depth",
      "Handle return" in pii.mask_json(items_page, vault, tool="mcp__tracker__get_board_items_page"))
check("readable fields: a CPF inside a kept title is still masked", cpf_formatted not in readable and "Refund CPF#" in readable)
check("readable fields: a person outside the listed paths is still masked", "Maria Silva" not in readable)
check("readable fields: another tool with the same shape is still masked",
      "Handle return" not in pii.mask_json(tracker, vault, tool="mcp__other__read"))
check("readable fields: a rule without a tool is ignored", pii.parse_field_rules(("**.items[].name",)) == ())
pii.READABLE_FIELDS = ()
os.environ["CLAUDE_PLUGIN_OPTION_READABLE_FIELDS"] = json.dumps(tracker_rules)
from_hook = hook("post", {"tool_name": "mcp__tracker__all_api_read", "tool_response": [{"type": "text", "text": tracker}]})
del os.environ["CLAUDE_PLUGIN_OPTION_READABLE_FIELDS"]
check("readable fields: the hook keeps a listed title and masks the person", "Handle return outcomes" in from_hook and "Maria Silva" not in from_hook)

people = lambda text: json.dumps({"items": [{"id": "1", "column_values": [
    {"id": "person", "type": "people", "text": text}, {"id": "status", "type": "status", "text": "Done"}]}]})
two = pii.mask_json(people("Maria Silva, Joao Souza"), vault, tool="mcp__tracker__all_api_read")
one = pii.mask_json(people("Maria Silva"), vault, tool="mcp__tracker__all_api_read")
check("people column: every person is masked", "Maria" not in two and "Joao" not in two)
check("people column: each person keeps one token across tasks", json.loads(one)["items"][0]["column_values"][0]["text"] in two)
check("people column: other columns are kept", '"Done"' in two)
record = '{"id": 1, "name": "Maria Silva"}'
check("JSON after a label is masked by key", "Maria" not in pii.mask_json(f"Result: {record}", vault))
check("JSON in a code block is masked by key", "Maria" not in pii.mask_json(f"Here it is:\n```json\n{record}\n```\n", vault))
check("JSON on its own line inside a log is masked by key", "Maria" not in pii.mask_json(f"2026-10-22 got\n  {record}\nend", vault))
check("text around embedded JSON is kept", pii.mask_json(f"Result: {record} done", vault).startswith("Result: {") and pii.mask_json(f"Result: {record} done", vault).endswith("} done"))
pretty = "log:\n" + json.dumps({"rows": [{"id": 1, "name": "Maria Silva"}]}, indent=2) + "\nend"
check("multi-line JSON inside text is masked by key", "Maria" not in pii.mask_json(pretty, vault))
ndjson = "\n".join(json.dumps({"id": i, "name": f"Maria {i}"}) for i in range(3))
check("NDJSON is masked by key, line by line", "Maria" not in pii.mask_json(ndjson, vault))
check("deep nesting inside text does not break masking", cpf not in pii.mask_json("x\n" + "[\n" * 5000 + cpf, vault))
code = "function f(x) { return { name: x } }\nconst a = [1, 2]"
check("code with braces is left alone", pii.mask_json(code, vault) == code)
pii.READABLE_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values[].text",))
check("people column: a readable rule keeps the names", "Maria Silva" in pii.mask_json(people("Maria Silva"), vault, tool="mcp__tracker__x"))
pii.READABLE_FIELDS = ()

board = lambda client: json.dumps({"items": [{"id": "1", "column_values": [
    {"id": "person", "type": "people", "text": "Maria Silva"},
    {"id": "text_client", "type": "text", "text": client},
    {"id": "text_note", "type": "text", "text": "call back friday"}]}]})
column_text = lambda out, column: next(c["text"] for c in json.loads(out)["items"][0]["column_values"] if c["id"] == column)
pii.READABLE_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values[type=people].text",))
kept = pii.mask_json(board("Acme Comercio Ltda"), vault, tool="mcp__tracker__x")
check("field filter: [type=people] keeps the person", column_text(kept, "person") == "Maria Silva")
pii.READABLE_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values[].text",))
pii.MASKED_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values[id=text_client].text",))
first = pii.mask_json(board("Acme Comercio Ltda"), vault, tool="mcp__tracker__x")
second = pii.mask_json(board("Acme Comercio Ltda"), vault, tool="mcp__tracker__y")
check("masked fields: the listed column becomes a token", column_text(first, "text_client").startswith("NAME#"))
check("masked fields: the same client gets the same token", column_text(first, "text_client") == column_text(second, "text_client"))
check("masked fields: masking wins over a readable rule", "Acme" not in first)
check("masked fields: other columns are kept", column_text(first, "text_note") == "call back friday")
check("masked fields: another tool is not affected", "Acme" in pii.mask_json(board("Acme Comercio Ltda"), vault, tool="mcp__other__x"))
pii.READABLE_FIELDS = pii.MASKED_FIELDS = ()
os.environ["CLAUDE_PLUGIN_OPTION_MASKED_FIELDS"] = "mcp__tracker__:**.column_values[id=text_client].text"
from_hook = hook("post", {"tool_name": "mcp__tracker__all_api_read", "tool_response": [{"type": "text", "text": board("Acme Comercio Ltda")}]})
del os.environ["CLAUDE_PLUGIN_OPTION_MASKED_FIELDS"]
check("masked fields: the hook reads the option", "Acme" not in from_hook and "call back friday" in from_hook)

# Terms the user lists (a client's company, a person): every variant becomes a TERM# token, and nothing else changes.
check("terms: off by default", pii.TERM_RE is None and pii.mask_text("openvpn.zorbtech.example", vault) == "openvpn.zorbtech.example")
pii.TERM_RE = pii.compile_terms(["Zorbtech", "Metabolix", "Ana", "Brasília Labs"])
term_cases = {
    "inside a domain": "openvpn.zorbtech.example",
    "inside a file name": "./vpn/cliente-ZorbTech.ovpn",
    "upper case": "ZORBTECH",
    "a separator between letters": "z.o.r.b-t_e_c_h",
    "without the accent": "brasilia labs",
    "joined by a hyphen": "BRASÍLIA-LABS",
    "a short term as a word": "oi Ana!",
    "a short term in an identifier": "ana_api",
}
for label, text in term_cases.items():
    check(f"terms: {label} is masked", "TERM#" in pii.mask_text(text, vault))
for label, text in {"a short term inside a word": "banana e Anabela", "a common word that starts a term": "uma meta clara",
                    "a token's hex": "CPF#ab12cd34ef56 ana", "two words that spell a term": "zorb techno"}.items():
    masked = pii.mask_text(text, vault)
    check(f"terms: {label} is kept", masked.split(" ")[0] == text.split(" ")[0] and "banana" in masked if "banana" in text
          else masked.split(" ")[0] == text.split(" ")[0])
domain = pii.mask_text("openvpn.zorbtech.example", vault)
check("terms: the rest of the domain is kept", domain.startswith("openvpn.TERM#") and domain.endswith(".example"))
check("terms: the same spelling gets the same token", pii.mask_text("Zorbtech", vault) == pii.mask_text("Zorbtech!", vault)[:-1])
check("terms: many spellings never collide", len({pii.mask_text(t, vault) for t in ("zorbtech", "ZORBTECH", "ZorbTech", "Zorbtech", "zorbTECH", "ZoRbTeCh")}) == 6)
check("terms: the token gives back the exact spelling", pii.unmask_text(pii.mask_text("Zorb-Tech", vault), vault) == "Zorb-Tech")
check("terms: masking twice changes nothing", pii.mask_text(domain, vault) == domain)
check("terms: the token is recognized everywhere", pii.TOKEN_RE.fullmatch(pii.mask_text("Metabolix", vault)) is not None)
pii.TERM_RE = None
os.environ["CLAUDE_PLUGIN_OPTION_TERMS"] = '["Zorbtech"]'
from_hook = hook("post", {"tool_name": "Bash", "tool_response": {"stdout": "remote openvpn.zorbtech.example 1194", "stderr": ""}})
del os.environ["CLAUDE_PLUGIN_OPTION_TERMS"]
check("terms: the hook reads the option", "zorbtech" not in from_hook.lower() and "TERM#" in from_hook)

# IP addresses: kept by default (above), masked when the option is on.
pii.MASK_IP = True
check("IP: masked, the final period kept", re.fullmatch(r"DNS IP#[0-9a-f]{12}\.", pii.mask_text("DNS 10.1.2.3.", vault)) is not None)
for kept in ("127.0.0.1", "0.0.0.0", "255.255.255.0", "999.1.1.1", "v1.2.3.4", "1.2.3.4.5", "10.1.2"):
    check(f"IP: {kept} is kept", pii.mask_text(f"x {kept} y", vault) == f"x {kept} y")
check("IP: an IP with CPF check digits becomes an IP token", pii.mask_text(f"host {ip_like} up", vault).startswith("host IP#"))
check("IP: the token gives the address back", pii.unmask_text(pii.mask_text("10.9.8.7", vault), vault) == "10.9.8.7")
pii.MASK_IP = False

# The same email or name in other cases shares one token; before, the 4th spelling raised and the output was suppressed.
spellings = {pii.mask_text(e, vault) for e in ("caio@mail.test", "Caio@mail.test", "CAIO@mail.test", "caio@MAIL.test", "Caio@Mail.Test")}
check("email: five spellings share one token", len(spellings) == 1)
names = {vault.token_for("NAME", n) for n in ("Caio Prado", "CAIO PRADO", "caio prado", "Caio prado")}
check("name: four spellings share one token", len(names) == 1)

# A file named after an email keeps its extension.
check("email: a file name keeps its extension", re.fullmatch(r"\./EMAIL#[0-9a-f]{12}\.txt", pii.mask_text("./ana.silva@mail.test.txt", vault)) is not None)
check("email: the same address with and without the extension", pii.mask_text("ana.silva@mail.test.txt", vault)[:-4] == pii.mask_text("ana.silva@mail.test", vault))
check("email: a domain of three labels is whole", pii.unmask_text(pii.mask_text("bia@mail.com.test", vault), vault) == "bia@mail.com.test")
check("email: an extension-like label in the middle stays in", pii.unmask_text(pii.mask_text("bia@x.pdf.test", vault), vault) == "bia@x.pdf.test")
check("email: an allowed domain with an extension is kept", pii.mask_text("bia@acme.example.csv", vault) == "bia@acme.example.csv")

# Some tools return column_values as a map keyed by column id, not a list.
flat_board = json.dumps({"board": {"id": "1", "name": "Dev tasks"}, "items": [{"id": "2", "name": "Handle return outcomes",
    "column_values": {"person": "Maria Silva", "text_client": "Acme Comercio Ltda", "status": "Done"}}]})
pii.MASKED_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values[id=text_client].text",))
check("map-shaped columns: a list-shaped rule does not reach them (the 22/10 leak)",
      "Acme" in pii.mask_json(flat_board, vault, tool="mcp__tracker__get_board_items_page"))
pii.MASKED_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values.text_client",))
pii.READABLE_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.board.name", "mcp__tracker__:**.items[].name"))
flat_out = pii.mask_json(flat_board, vault, tool="mcp__tracker__get_board_items_page")
check("map-shaped columns: a map-shaped rule masks the client", "Acme" not in flat_out and "NAME#" in flat_out)
check("map-shaped columns: board.name and item titles are kept", "Dev tasks" in flat_out and "Handle return outcomes" in flat_out)
check("map-shaped columns: other columns are kept", '"Done"' in flat_out)
pii.READABLE_FIELDS = pii.MASKED_FIELDS = ()
check("person field is masked by default", "Maria" not in pii.mask_json(flat_board, vault, tool="mcp__tracker__get_board_items_page"))
check("people0 and pessoas fields are masked by default",
      all(pii.column_kind(c) == "NAME" for c in ("person", "people", "people0", "pessoas", "assigned_person")))
check("person ids and person objects are kept", pii.mask_json('{"person": 42, "person_id": 7}', vault) == '{"person": 42, "person_id": 7}')
pii.READABLE_FIELDS = pii.parse_field_rules(("mcp__tracker__:**.column_values.person",))
check("person field: a readable rule keeps it", "Maria Silva" in pii.mask_json(flat_board, vault, tool="mcp__tracker__get_board_items_page"))
pii.READABLE_FIELDS = ()

email_prompt = hook("prompt", {"prompt": "the customer is maria@cliente.example"})
check("prompt with an external email blocked", '"block"' in email_prompt and "pii-allow EMAIL#" in email_prompt)
config_path = SANDBOX / "pii-tokens" / "config.json"
allowed_email = pii.Vault(store=False).token_for("EMAIL", "partner@corp.example.net")
allowed_cpf = pii.Vault(store=False).token_for("CPF", cpf)
refused = subprocess.run(["python3", str(SCRIPTS / "cli.py"), "pii-allow", allowed_email], capture_output=True, text=True)
check("pii-allow refuses to add outside an interactive terminal", refused.returncode != 0 and not config_path.read_text().count("allowed_tokens"))
import cli as cli_module  # noqa: E402
cli_module.sys.stdout.isatty = lambda: True
cli_module.cmd_allow([allowed_email, allowed_cpf])
check("pii-allow writes the tokens", allowed_email in json.loads(config_path.read_text())["allowed_tokens"])
check("pii-allow rejects a value that is not a token",
      subprocess.run(["python3", str(SCRIPTS / "cli.py"), "pii-allow", "maria@cliente.example"], capture_output=True, text=True).returncode != 0)
for command in ("pii-sheet", "pii-reveal"):
    bare = subprocess.run(["python3", str(SCRIPTS / "cli.py"), command], capture_output=True, text=True)
    check(f"{command} without a file prints its usage", bare.returncode != 0 and f"usage: {command} FILE" in bare.stderr and "Traceback" not in bare.stderr)
check("allowed email passes the prompt", hook("prompt", {"prompt": "write to partner@corp.example.net"}) == "")
out = hook("post", {"tool_name": "Bash", "tool_response": {"stdout": f"cnpj of us {cpf_formatted}", "stderr": ""}})
check("allowed value is not masked in tool output", out == "" or cpf_formatted in out)
check("other values still masked with an allowlist",
      "EMAIL#" in hook("post", {"tool_name": "Bash", "tool_response": {"stdout": "x stranger@corp.example.net", "stderr": ""}}))
subprocess.run(["python3", str(SCRIPTS / "cli.py"), "pii-allow", "--remove", allowed_cpf], capture_output=True, text=True)
check("pii-allow --remove takes it back", "CPF#" in hook("post", {"tool_name": "Bash", "tool_response": {"stdout": f"x {cpf_formatted}", "stderr": ""}}))
check("config file is private", oct(config_path.stat().st_mode & 0o777) == "0o600")

repo = SANDBOX / "repo"
(repo / "notes").mkdir(parents=True)
subprocess.run(["git", "init", "-q", str(repo)], check=True)
(repo / ".gitignore").write_text("notes/\n")
live_token = vault.token_for("CPF", fake_cpf(11))
example_token = "CPF#3f1a9c0d22e4"
def write_event(path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}
check("writing a live token into a repository file asks first", '"ask"' in hook("pre", write_event(repo / "spec.py", f"X = '{live_token}'")))
check("an Edit with a live token asks too",
      '"ask"' in hook("pre", {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "spec.py"), "old_string": "a", "new_string": live_token}}))
check("an example token that is not in the vault passes", hook("pre", write_event(repo / "README.md", f"like {example_token}")) == "")
check("a git-ignored file passes (pii-reveal flow, notes)", hook("pre", write_event(repo / "notes" / "case.md", live_token)) == "")
check("a file outside any repository passes", hook("pre", write_event(SANDBOX / "loose.md", live_token)) == "")
check("a commit message with a live token asks first",
      '"ask"' in hook("pre", {"tool_name": "Bash", "tool_input": {"command": f"git commit -m 'fix {live_token}'"}}))
exec_asks = hook("pre", {"tool_name": "Bash", "tool_input": {"command": f"pii-exec -- curl https://x.example/?d={live_token}"}})
check("pii-exec with a token asks the user first", '"permissionDecision": "ask"' in exec_asks and "real values" in exec_asks)
check("pii-exec --stdin asks the user first", '"ask"' in hook("pre", {"tool_name": "Bash", "tool_input": {"command": "cat q.txt | pii-exec --stdin -- psql"}}))
check("pii-exec without a token passes", hook("pre", {"tool_name": "Bash", "tool_input": {"command": "pii-exec -- ls"}}) == "")
check("other Bash commands with a token pass", hook("pre", {"tool_name": "Bash", "tool_input": {"command": f"grep {live_token} x.log"}}) == "")
check("writes without tokens pass", hook("pre", write_event(repo / "spec.py", "X = 1  # see issue #12")) == "")

slow = SANDBOX / "slow_hook.py"
slow.write_text(
    f"import json, sys, time\nsys.path.insert(0, {str(SCRIPTS)!r})\nimport pii, hook\n"
    "hook.DEADLINE_SECONDS = 1\npii.mask_json = lambda *a, **k: time.sleep(5)\n"
    "hook.post(json.load(sys.stdin))\n"
)
out = subprocess.run(["python3", str(slow)], input=json.dumps({"tool_name": "Bash", "tool_response": bash_shape}),
                     capture_output=True, text=True, timeout=4).stdout
check("deadline suppresses instead of leaking", "suppressed" in out and '"x"' not in out)

broken = SANDBOX / "broken"
broken.mkdir()
(broken / "pii.py").write_text("raise ImportError('broken install')\n")
(broken / "hook.py").write_text((SCRIPTS / "hook.py").read_text())
out = subprocess.run(["python3", str(broken / "hook.py"), "post"], input=json.dumps({"tool_name": "Bash", "tool_response": bash_shape}),
                     capture_output=True, text=True).stdout
check("a broken library suppresses instead of leaking", "suppressed" in out and '"x"' not in out)

import shutil  # noqa: E402

RUN_SH = str(SCRIPTS / "run.sh")


def stub_venv(root, label):
    python = root / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!/bin/sh\necho {label}\n")
    python.chmod(0o755)
    return root


def run_sh(**env):
    clean = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PLUGIN_DATA", "CLAUDE_CONFIG_DIR")}
    return subprocess.run([RUN_SH, "cli.py"], env={**clean, **env}, capture_output=True, text=True).stdout.strip()


config_dir = SANDBOX / "claude"
stub_venv(config_dir / "plugins" / "data" / "pii-tokens-pii-tokens", "data-dir-venv")
plugin_data = stub_venv(SANDBOX / "plugin-data", "plugin-data-venv")
check("without CLAUDE_PLUGIN_DATA, run.sh finds the plugin venv", run_sh(CLAUDE_CONFIG_DIR=str(config_dir)) == "data-dir-venv")
check("CLAUDE_PLUGIN_DATA wins over the lookup",
      run_sh(CLAUDE_CONFIG_DIR=str(config_dir), CLAUDE_PLUGIN_DATA=str(plugin_data)) == "plugin-data-venv")
check("without any venv, run.sh falls back to system python3",
      "venv" not in run_sh(CLAUDE_CONFIG_DIR=str(SANDBOX / "empty")))

setup_data = SANDBOX / "setup-data"
setup_data.mkdir()
shutil.copy(SCRIPTS.parent / "requirements.txt", setup_data / "requirements.txt")
subprocess.run([str(SCRIPTS / "setup.sh")], env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(SCRIPTS.parent), "CLAUDE_PLUGIN_DATA": str(setup_data)})
linked = subprocess.run([str(setup_data / "bin" / "pii-mask")], input="plain text", capture_output=True, text=True)
check("setup.sh links the commands at a path that survives updates", linked.stdout.strip() == "plain text")

old_mac = SANDBOX / "old-mac-bin"
old_mac.mkdir()
real_readlink = shutil.which("readlink")
(old_mac / "readlink").write_text(f'#!/bin/sh\n[ "$1" = "-f" ] && {{ echo "readlink: illegal option -- f" >&2; exit 1; }}\nexec {real_readlink} "$@"\n')
(old_mac / "readlink").chmod(0o755)
links = SANDBOX / "links"
links.mkdir()
(links / "relative").symlink_to(os.path.relpath(SCRIPTS.parent / "bin" / "pii-mask", links))
(links / "absolute").symlink_to(SCRIPTS.parent / "bin" / "pii-mask")
(links / "chain").symlink_to(links / "relative")
for link in ("relative", "absolute", "chain"):
    ran = subprocess.run([str(links / link)], input="plain text", capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{old_mac}:{os.environ['PATH']}"})
    check(f"a command reached through a {link} link runs without readlink -f", ran.stdout.strip() == "plain text")

home = SANDBOX / "home"
reveal_dir = home / ".cache" / "pii-tokens" / "reveal"
reveal_dir.mkdir(parents=True)
(reveal_dir / "old.md").write_text("revealed two days ago")
os.utime(reveal_dir / "old.md", (time.time() - 48 * 3600,) * 2)
(reveal_dir / "fresh.md").write_text("revealed a minute ago")
subprocess.run([str(SCRIPTS / "setup.sh")], env={**os.environ, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(SCRIPTS.parent), "CLAUDE_PLUGIN_DATA": str(setup_data)})
check("session start deletes revealed copies older than 24h", not (reveal_dir / "old.md").exists())
check("session start keeps a fresh revealed copy", (reveal_dir / "fresh.md").exists())

scrub_cpf = fake_cpf(424242)
transcript = SANDBOX / "claude-config" / "projects" / "some-project" / "session.jsonl"
transcript.parent.mkdir(parents=True)
transcript.write_text(json.dumps({"type": "user", "message": {"content": f"check {scrub_cpf}"}}) + "\n")
os.utime(transcript, (time.time() - 3600,) * 2)
subprocess.run(["python3", str(SCRIPTS / "cli.py"), "pii-scrub", "--apply"], env={**os.environ, "CLAUDE_CONFIG_DIR": str(SANDBOX / "claude-config")}, capture_output=True, text=True)
scrubbed = transcript.read_text()
scrub_token = pii.TOKEN_RE.search(scrubbed)
check("pii-scrub replaces the value in an old transcript", scrub_cpf not in scrubbed and scrub_token is not None)
check("pii-scrub keeps the value reversible", scrub_token is not None and pii.Vault(store=False).value_for(scrub_token.group(0)) == scrub_cpf)

import image as image_module  # noqa: E402

if image_module.available():
    import base64
    import io
    import uuid

    from PIL import Image, ImageDraw, ImageFont

    def screenshot(value):
        picture = Image.new("RGB", (700, 60), "white")
        ImageDraw.Draw(picture).text((10, 20), f"2U29   Registered   {value}   R$ 35.294,00",
                                     font=ImageFont.load_default(size=16), fill="black")
        out = io.BytesIO()
        picture.save(out, "PNG")
        return out.getvalue()

    def read_image(data):
        return {"type": "image", "file": {"base64": base64.b64encode(data).decode(), "type": "image/png",
                                          "originalSize": len(data), "dimensions": {"originalWidth": 700}}}

    def digits_seen(data):
        picture = Image.open(io.BytesIO(data))
        enlarged = io.BytesIO()
        picture.resize((picture.width * 3, picture.height * 3)).save(enlarged, "PNG")
        return "".join(c for w in image_module._words(enlarged.getvalue()) for c in w["text"] if c.isdigit())

    image_cnpj = fake_cnpj(5150)
    formatted_cnpj = f"{image_cnpj[:2]}.{image_cnpj[2:5]}.{image_cnpj[5:8]}/{image_cnpj[8:12]}-{image_cnpj[12:]}"
    with_cnpj = screenshot(formatted_cnpj)
    check("image control: OCR reads the CNPJ in the test image", image_cnpj in digits_seen(with_cnpj))

    out = json.loads(hook("post", {"tool_name": "Read", "tool_input": {"file_path": "/tmp/shot.png"},
                                   "tool_response": read_image(with_cnpj)}))["hookSpecificOutput"]
    masked_image = base64.b64decode(out["updatedToolOutput"]["file"]["base64"])
    image_token = pii.Vault(store=False).token_for("CNPJ", image_cnpj)
    check("Read of an image: the CNPJ is no longer readable in it", image_cnpj not in digits_seen(masked_image))
    check("Read of an image: the output keeps the image shape",
          out["updatedToolOutput"]["file"].keys() == read_image(with_cnpj)["file"].keys())
    check("Read of an image: the note names the token", image_token in out["additionalContext"])
    check("Read of an image: the token is reversible", pii.Vault(store=False).value_for(image_token) == image_cnpj)
    check("Read of an image without personal data: untouched",
          hook("post", {"tool_name": "Read", "tool_input": {}, "tool_response": read_image(screenshot("R$ 1.234,00"))}) == "")
    broken = json.loads(hook("post", {"tool_name": "Read", "tool_input": {},
                                      "tool_response": {"type": "image", "file": {"base64": "AAAA", "type": "image/png"}}}))
    check("Read of an image that fails to mask: withheld as a blank image",
          broken["hookSpecificOutput"]["updatedToolOutput"]["file"]["base64"] == hook_module.BLANK_PNG)

    shot_b64 = base64.b64encode(with_cnpj).decode()
    browser = [{"type": "text", "text": f"Screenshot of the page, customer {fake_cpf(77)}"},
               {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": shot_b64}}]
    out = json.loads(hook("post", {"tool_name": "mcp__playwright__browser_take_screenshot", "tool_input": {},
                                   "tool_response": browser}))["hookSpecificOutput"]
    masked_browser = out["updatedToolOutput"]
    check("browser screenshot (MCP content blocks): the image is masked",
          image_cnpj not in digits_seen(base64.b64decode(masked_browser[1]["source"]["data"])))
    check("browser screenshot: the text next to it is masked too", fake_cpf(77) not in masked_browser[0]["text"])
    check("browser screenshot: the shape is kept",
          [b["type"] for b in masked_browser] == ["text", "image"] and masked_browser[1]["source"]["media_type"] == "image/png")
    raw_mcp = {"content": [{"type": "image", "data": shot_b64, "mimeType": "image/png"}]}
    out = json.loads(hook("post", {"tool_name": "mcp__other__shot", "tool_input": {}, "tool_response": raw_mcp}))
    check("MCP image block with data and mimeType: masked",
          image_cnpj not in digits_seen(base64.b64decode(out["hookSpecificOutput"]["updatedToolOutput"]["content"][0]["data"])))

    no_ocr_bin = SANDBOX / "no-ocr-bin"
    no_ocr_bin.mkdir()
    for tool in ("git",):
        if shutil.which(tool):
            (no_ocr_bin / tool).symlink_to(shutil.which(tool))
    no_ocr = subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "post"], capture_output=True, text=True,
                            env={**os.environ, "PATH": str(no_ocr_bin)},
                            input=json.dumps({"tool_name": "Read", "tool_input": {}, "tool_response": read_image(with_cnpj)})).stdout
    check("without tesseract: Claude is told the image was not checked", hook_module.IMAGE_UNCHECKED in no_ocr)

    session = str(uuid.uuid4())
    project = SANDBOX / "claude-config" / "projects" / f"pii-tokens-test-{session[:8]}"
    pasted_dir = Path(tempfile.gettempdir()) / f"claude-{os.getuid()}" / project.name / session / "images"
    pasted_dir.mkdir(parents=True)
    (pasted_dir / "1.png").write_bytes(with_cnpj)
    (pasted_dir / "2.png").write_bytes(screenshot("R$ 1.234,00"))
    pasted = {"session_id": session, "transcript_path": str(project / f"{session}.jsonl"), "cwd": str(SANDBOX)}
    fake_bin = SANDBOX / "fake-clipboard"
    fake_bin.mkdir()
    clipboard = SANDBOX / "clipboard.txt"
    for tool in ("wl-copy", "xclip", "pbcopy"):
        (fake_bin / tool).write_text(f"#!/bin/sh\ncat > {clipboard}\n")
        (fake_bin / tool).chmod(0o755)
    real_path = os.environ["PATH"]
    os.environ["PATH"] = f"{fake_bin}:{real_path}"
    blocked_paste = hook("prompt", {**pasted, "prompt": "[Image #1] what is this?"})
    check("pasted image with a CNPJ: prompt blocked, pointing to the file to read",
          '"block"' in blocked_paste and str(pasted_dir / "1.png") in blocked_paste)
    check("pasted image with a CNPJ: the read request, question included, goes to the clipboard",
          clipboard.read_text() == f"Read {pasted_dir / '1.png'}. what is this?")
    clipboard.unlink()
    os.environ["CLAUDE_PLUGIN_OPTION_COPY_READ_REQUEST"] = "false"
    check("copy_read_request off: still blocked, clipboard untouched",
          '"block"' in hook("prompt", {**pasted, "prompt": "[Image #1]"}) and not clipboard.exists())
    del os.environ["CLAUDE_PLUGIN_OPTION_COPY_READ_REQUEST"]
    check("pasted image without personal data: prompt passes", hook("prompt", {**pasted, "prompt": "[Image #2] and this?"}) == "")
    check("pasted image with the escape word: prompt passes", hook("prompt", {**pasted, "prompt": "[Image #1] pii-ok"}) == "")
    os.environ["PATH"] = real_path

    real_check = image_module.has_personal_data

    def too_slow(data):
        raise TimeoutError("deadline")

    image_module.has_personal_data = too_slow
    timed_out, _ = hook_module._pasted_images_to_block({**pasted, "prompt": "[Image #1] [Image #2]"})
    image_module.has_personal_data = real_check
    check("pasted images not checked in time: all blocked, none sent unchecked", len(timed_out) == 2)
    shutil.rmtree(pasted_dir.parent.parent, ignore_errors=True)
else:
    print("skip image tests: tesseract or Pillow missing")

import keyring  # noqa: E402

for name in ("hmac", "vault"):
    try:
        keyring.delete_password("pii-tokens-test", name)
    except keyring.errors.PasswordDeleteError:
        pass
shutil.rmtree(SANDBOX, ignore_errors=True)

print("failures:", failures)
sys.exit(1 if failures else 0)
