# Cenários de teste manuais

O que só se testa à mão, no ambiente real. A lógica (máscara, formatos, comandos, extensão com servidor falso) está nos testes automáticos de `tests/` e não se repete aqui.

Cada PR roda os cenários do lugar que ele mexe e atualiza a data. Cenário que ganha teste automático diz onde está, e sai da lista manual.

**Como testar sem se enganar:**
- Dado sempre fictício.
- O dado nasce no arquivo ou no banco, nunca na pergunta: o que se digita o Claude lê.
- O nome do arquivo não pode entregar a resposta (um `app-pontuado.log` faz o Claude pular o caminho testado).
- A prova é a transcrição da sessão ou a resposta bruta, não o print.

## Windows, terminal

| cenário | passo | esperado | último teste | automatizado? |
|---|---|---|---|---|
| comandos no PowerShell | rodar a linha do PATH de `docs/usage.md` e abrir um PowerShell novo | `pii-reveal` é achado (`pii-reveal.cmd`) | 01/11/2026 | não |
| revelar um arquivo | `pii-reveal arquivo` com um token | abre no Notepad com o valor real | 01/11/2026 | não |
| revelar um `.bat` | `pii-reveal teste.bat` com um token | abre no Notepad e não executa | 01/11/2026 | não |
| sem o venv | renomear o venv do plugin e rodar `pii-mask` | funciona pelo Python do sistema | 01/11/2026 | lógica: `tests/test_pii.py` |
| planilha | `pii-sheet clientes.xlsx` | CPF e email como token, 0 cru | 01/11/2026 | não |
| ver um valor | `pii-unmask CPF#...` num terminal | mostra o valor | 01/11/2026 | não |

## Claude Desktop, modo Code (Windows)

| cenário | passo | esperado | último teste | automatizado? |
|---|---|---|---|---|
| ler arquivo com dado | pedir para ler um arquivo com CPF e email | só tokens na transcrição | 01/11/2026 | no Linux: `pii-selfcheck` |
| CPF com pontos num log | pedir as linhas do CPF de um cliente num log que escreve com pontos | acha as linhas (`.fmt`) | 01/11/2026 | lógica: `tests/test_pii.py` |
| CPF que não está no log | pedir um CPF ausente | "não aparece", procurado com e sem pontuação | 01/11/2026 | não |
| valor real | "qual o CPF real do Fulano?" | abre no editor, com pontuação, sem `.fmt`; o número não aparece no chat | 01/11/2026 | não |
| uso do dia a dia | "quantos clientes tem no arquivo?" | responde sem falar de máscara | 01/11/2026 | não |
| print colado | colar print com CPF e enviar; depois "oi"; depois Ctrl+V e Enter | barrado; "oi" passa; a leitura traz os CPFs como token, inclusive com o cursor no número | 01/11/2026 | lógica: `tests/test_pii.py` |

## Claude Desktop, modo chat (extensão, Windows)

| cenário | passo | esperado | último teste | automatizado? |
|---|---|---|---|---|
| consulta ao Metabase | "liste 3 clientes da tabela PEOPLE com nome, email e cidade" | nome e email como token, cidade normal | 01/11/2026 | lógica: `tests/test_desktop.py` |
| texto do próprio servidor | servidor de teste com CPF na descrição da ferramenta e como nome de campo | só tokens | 01/11/2026 | lógica: `tests/test_desktop.py` |
| sair do login | com o Desktop fechado, apagar a pasta `oauth` e abrir | pede login de novo; depois a consulta vem com tokens | 01/11/2026 | não |
| trocar a configuração | mudar a URL da extensão | só vale depois de fechar e abrir o Desktop | 01/11/2026 | não |

## Ainda sem teste

- macOS, no terminal e no Desktop.
- Servidor MCP real além do Metabase.
- Redirect de https para http na extensão (coberto só pelo teste automático).
