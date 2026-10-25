# Usando o pii-tokens

Detalhes de instalação e notas sobre os comandos. A versão curta está no [README](../README.md).

## Primeira sessão

- O cofre de chaves do sistema é o Keychain no macOS e o Secret Service no Linux com interface gráfica.

Na primeira sessão, o plugin instala as dependências dele, fixadas por hash, no diretório de dados.

- Se isso falhar, a máscara continua, mas os tokens aparecem como `CPF#????????` e não voltam.

Para mascarar imagem, instale o `tesseract` (`apt install tesseract-ocr` ou `brew install tesseract`).

## Conferir se funciona

Rode `pii-selfcheck` depois de instalar, e de novo a cada atualização do Claude Code.

- Uma atualização pode quebrar a máscara sem dar erro nenhum.
- Ele abre sessões sem interface com um CPF fictício e mostra o que o modelo recebeu.
- Precisa do CLI `claude` e custa algumas chamadas pequenas ao modelo.

## Comandos

| Você quer | Comando | Quem roda |
|---|---|---|
| Rodar um comando com o valor real | `pii-exec -- grep CPF#3f1a9c0d22e4 app.log` | o Claude ou você |
| Abrir um arquivo com os valores reais | `pii-reveal relatorio.md` | o Claude ou você |
| Ler um XLSX | `pii-sheet arquivo.xlsx` | o Claude ou você |
| Conferir se a máscara funciona | `pii-selfcheck` | o Claude ou você |
| Consultar um token | `pii-unmask CPF#3f1a9c0d22e4` | só você |
| Parar de mascarar um valor | `pii-allow EMAIL#91bd0e4a7c13` | só você |

## Os comandos no seu terminal

Os comandos `pii-*` já estão no PATH do Claude. Para rodar no seu terminal, adicione uma vez, no perfil do seu shell:

```
export PATH="$HOME/.claude/plugins/data/pii-tokens-pii-tokens/bin:$PATH"
```

- `pii-unmask` e `pii-allow` só funcionam assim: rodam em terminal interativo, para o Claude não usar sozinho.
- A pasta é um link que o plugin refaz a cada sessão, então sobrevive às atualizações.

## Configurações

Todas opcionais. Pedidas quando o plugin é ativado, alteráveis depois com `claude plugin configure pii-tokens@pii-tokens`.

- **Domínios de email liberados:** domínios que ficam visíveis, como o da sua empresa.
	- Já vêm liberados, sem configurar: `example.com`, `example.org` e os endereços `noreply` do GitHub.
- **Ferramentas que devolvem tabela:** prefixos de ferramentas MCP que devolvem tabela no formato do psql.
	- Exemplo: `mcp__postgres__`.
	- As colunas delas são mascaradas pelo nome (`nome`, `razao_social`, `email`, ...).
- **Copiar o pedido de leitura:** ligada por padrão. Quando uma imagem colada é barrada, a mensagem que pede a leitura do arquivo vai para a área de transferência, no lugar do que estava lá.
- **Manter nomes de ferramenta de dev:** desligada por padrão. Veja [Efeitos colaterais](limits.md#efeitos-colaterais).
- **Campos legíveis:** campos que você sabe que não guardam nome de pessoa, numa ferramenta só. Formato `ferramenta:caminho`.
	- Exemplo, para ler o título das tarefas num MCP de gestão de tarefas: `mcp__tracker__:**.items[].name`, `mcp__tracker__:**.subitems[].name`, `mcp__tracker__:**.boards[].name`.
	- `**.` casa qualquer começo de caminho.
	- CPF, CNPJ, email e telefone escritos dentro do campo continuam virando token.
	- A regra vale para a ferramenta inteira. Se a mesma conta tem um quadro de clientes, o título das tarefas dele, que costuma ser o nome do cliente, também sai.
	- `[chave=valor]` antes do último campo filtra pelo vizinho: `mcp__tracker__:**.column_values[type=people].text` libera só a coluna de pessoas, não as colunas de texto.
- **Campos mascarados:** o contrário, para campo que guarda dado pessoal sem que o nome dele diga. Mesmo formato.
	- Exemplo, para uma coluna "Cliente": `mcp__tracker__:**.column_values[id=text_abc123].text`. O id da coluna aparece na resposta da ferramenta.
	- ⚠️ Cada ferramenta do mesmo MCP pode devolver outro formato. Uma pode trazer as colunas como lista (a regra acima) e outra como mapa: para ela, `mcp__tracker__:**.column_values.text_abc123`. Ponha as duas, e confira com a resposta real antes de confiar.
	- O nome do quadro pode vir em `boards[].name` numa ferramenta e em `board.name` na outra.
	- O valor vira token, e o mesmo cliente tem sempre o mesmo token, então dá para cruzar tarefas sem ver o nome.
	- Se um campo cair nas duas listas, ele é mascarado.

## Notas sobre os comandos

- **O `pii-exec` mascara a saída de novo,** então o valor real nunca volta para o Claude.
- **Todo `pii-exec` com token pede a sua confirmação,** inclusive no modo auto. Leia o comando: um `curl` ou outro comando de rede mandaria o dado real para fora, e uma página ou uma tarefa podem tentar induzir o Claude a isso.
	- Enquanto o comando roda, o valor real aparece na lista de processos (`ps`).
- **O `pii-reveal` abre a cópia no seu editor,** fora do alcance do Claude.
- **O `pii-allow` é para valor que pode ir:** o CNPJ da sua empresa, o seu próprio email no `git log`.
	- A lista guarda tokens, não valores, então o arquivo de config não tem dado pessoal.
	- `pii-allow --list` e `pii-allow --remove` cuidam da lista.
- **Texto com dado pessoal vai num arquivo, não no prompt.** Salve e passe o caminho.
	- Prompt com CPF, CNPJ, telefone com DDD ou email fora dos domínios liberados é barrado.
	- A mensagem do bloqueio traz o comando `pii-allow` de cada valor.
	- `@arquivo` com dado pessoal também é barrado, porque o `@` não passa por hook nenhum.
- **Token não entra no seu código.**
	- Antes de o Claude gravar um token real num arquivo do repositório ou num commit, você é consultado.
	- Token de exemplo em documentação e arquivo ignorado pelo git não são afetados.
	- Vale para as ferramentas de escrita e para `git commit`. Gravar pelo shell (`echo ... > arquivo`, `tee`) não passa pela consulta.

O plugin traz também uma skill que ensina esse fluxo ao Claude.

## Crédito

As notas do [l-mb/claude-code-redaction-hooks](https://github.com/l-mb/claude-code-redaction-hooks) sobre o que cada hook consegue mudar pouparam tempo aqui.

## Desenvolvimento

```
make test       # roda com cofre e config descartáveis
```

O `make install` copia os scripts para `~/.claude/hooks/pii`, para quem usa sem o plugin.

- Essa instalação lê `~/.config/pii-tokens/config.json`.
- Aceita as mesmas chaves das opções do plugin, mais `data_dir` e `keyring_service`.
