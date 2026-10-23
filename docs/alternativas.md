# Alternativas

Levantado em 14/10/2026, lendo o README de cada projeto, e reconferido e ampliado em 22/10/2026. Não instalamos nenhum. Achou erro ou um projeto que falta? Abra uma issue.

[Read in English](alternatives.md)

## O que separa o pii-tokens

- **Troca, não bloqueia.** O Claude segue trabalhando com o token no lugar do valor.
- **Reversível na sua máquina.** O cofre é cifrado e a chave fica no cofre de chaves do sistema.
- **Documento brasileiro.** CPF e CNPJ, inclusive o alfanumérico, com dígito verificador.
- **Sem modelo de IA local.** Só regex e validação: instala em segundos e não baixa modelo nenhum.

## Comparação

| Projeto | O que é | CPF/CNPJ | Dentro do Claude Code | Reversível | Onde é melhor que o pii-tokens |
|---|---|---|---|---|---|
| Inference hooks do Claude Enterprise, com Netskope, Palo Alto, Proofpoint ou Zscaler | DLP da empresa, em beta desde agosto de 2026 | depende do fornecedor | sim, só no plano Enterprise | não: permite ou bloqueia | política central para a empresa inteira |
| [tarja](https://github.com/macmaia/tarja) | biblioteca Python | sim, e mais 15 tipos brasileiros | não | sim, em memória | cobre mais tipos de documento e usa o contexto da frase |
| [lgpd-guard](https://github.com/arthurpenedo/lgpd-guard) | proxy compatível com a OpenAI, CLI e biblioteca | sim | não | sim, por sessão | acha nomes com NER |
| [claude-privacy-tool](https://github.com/pasqualepillitteri/claude-privacy-tool) | hook de prompt e servidor MCP, com modelo de 1,5B | não citado | sim | sim | acha nomes e endereços em texto livre |
| [noirdoc](https://github.com/noirdoc-ai/mask-claude-plugin) | plugin que bloqueia a leitura e redige uma cópia | não (foco em alemão) | sim | sim, fora da sessão | lê PDF, PPTX e imagem |
| [claude-code-redaction-hooks](https://github.com/l-mb/claude-code-redaction-hooks) | hooks com regex | não | sim | não confirmado | foco em segredos, várias ações por regra |
| [redact-hook](https://github.com/SilentAutomaton/redact-hook) | um arquivo, só regex | não | sim | não | nenhuma dependência |
| [nopii](https://github.com/olafrv/nopii) | proxy por `ANTHROPIC_BASE_URL` | não | por proxy: a mensagem e a saída das ferramentas | sim | acha nomes com GLiNER |
| [claude-code-redact](https://github.com/paroque28/claude-code-redact) | proxy local | não citado | por proxy | sim | segredos e material sob NDA, regras por projeto |
| [JanuScope](https://github.com/giancarloerra/JanuScope) | proxy de MCP com política em YAML | não | só ferramentas MCP | não: troca por `[REDACTED]` | esconde ferramenta perigosa, trava escrita no SQL, auditoria; serve a outros clientes além do Claude Code |

## Para quem o pii-tokens não serve

- Precisa barrar a empresa inteira por política central: o caminho são os inference hooks do Enterprise.
- Precisa achar nome em texto livre: aqui o nome só é mascarado num campo que se chama como pessoa, em tabela ou JSON.
- Não usa o Claude Code: o `tarja` ou o `lgpd-guard` cabem em qualquer código.
