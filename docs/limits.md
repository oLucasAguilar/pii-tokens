# Limites

O que o pii-tokens não protege, o que a máscara estrita custa e o que fica sem máscara no seu disco. Leia antes de usar o plugin com dado pessoal real.

Isto protege contra exposição acidental, não contra um modelo tentando extrair dado. O Claude roda comandos como você: um modelo decidido, ou induzido por um texto malicioso, consegue ler o keyring e abrir o cofre, como o próprio plugin faz.

- Nos nossos testes, um modelo não conseguiu editar uma linha com CPF mascarado.
- Ele então imprimiu o arquivo com `od -c` e leu os dígitos.
- Em 22/10/2026, com pedidos feitos para extrair, o CPF também saiu invertido (`rev`) e com espaço entre os dígitos. A leitura comum, o arquivo inteiro e o base64 não vazaram.
- Comparação também revela: o mesmo valor gera sempre o mesmo token, então quem já sabe parte de um CPF pode imprimir os candidatos numerados e achar o que bate.

## O que passa

- **Comando que falha chega cru ao modelo.**
	- O hook que o Claude Code dispara na falha não consegue trocar a saída.
	- Pedido em [anthropics/claude-code#97278](https://github.com/anthropics/claude-code/issues/97278).
- **Nome em texto livre não é detectado:** corpo de issue, página web, linha de log.
- **Algumas formas de documento não são detectadas:**
	- telefone escrito como 11 dígitos corridos, a não ser em coluna de telefone
	- CPF colado em letras, como `doc` seguido dos dígitos
	- CPF quebrado em duas linhas
	- CPF escrito só com pontos (`123.156.189.09`) cujos três primeiros blocos vão até 255: tem forma de IP e passa (cerca de 2% desse formato; com hífen, sempre mascarado)
- **Segredos não são mascarados:** chave de API, senha, token de acesso, string de conexão. O plugin cuida de dado pessoal; para segredos, use junto uma ferramenta de segredos ([alternativas](alternativas.md)).
- **Comando com `!` não passa por hook nenhum.**
	- A saída entra direto no contexto, e não tem como ser barrado.
- **Imagem não é mascarada.** Print de uma tela com CPF passa.
- **Consulta montada para escapar dos nomes de campo passa.**
	- Função no SQL, como `SELECT reverse(cpf)`.
	- Campo renomeado, como `titulo: name` no GraphQL ou `AS titulo` no SQL.
- **A telemetria vê o original.**
	- O Claude Code registra a saída das ferramentas para o OpenTelemetry antes de os hooks rodarem.

Uma coisa falha fechada: se mascarar levar mais de 25 segundos ou quebrar, a saída é suprimida, não repassada.

## Efeitos colaterais

A máscara é estrita por padrão. Isso custa quando o que está na tela não é dado pessoal:

- **Campo `name` de JSON é sempre mascarado.**
	- Em `package.json`, `kubectl get -o json` ou `docker inspect`, o Claude vê `NAME#...` no lugar do nome.
	- Ligue **Manter nomes de ferramenta de dev** para deixar esses campos em paz.
	- Para título de tarefa (Monday, Asana, Trello), use **Campos legíveis** ([uso](usage.md#configurações)).
	- O campo só é mantido dentro de um documento com o formato exato de uma dessas ferramentas.
	- Então `{"name": "Maria Silva", "scripts": {}}` continua mascarado.
	- O que passa é um nome de uma palavra só dentro de um documento desses.
- **Campo `person`, `people` ou `pessoas` vira token por padrão** (o responsável no Monday, por exemplo). Para ler, use **Campos legíveis**.
- **Cerca de 1 em cada 100 números aleatórios de 11 ou 14 dígitos vira token.**
	- Eles passam no dígito verificador de CPF ou CNPJ: id de pedido, telefone sem pontuação, o último bloco da linha digitável de um boleto.
	- Rode pelo `pii-exec` o comando que precisa do número.
- **Cada chamada de ferramenta paga um processo Python.**
	- Cerca de 0,3 s para mascarar e 0,04 s para a checagem de escrita, medidos num notebook.

## O que fica no disco

A máscara decide o que chega ao modelo. No seu disco, algumas cópias ficam sem máscara:

- **Transcripts** (`~/.claude/projects/`) gravam do jeito que vieram:
	- o prompt barrado
	- a saída de comando que falhou
	- Saída mascarada é gravada mascarada.
	- `pii-scrub --apply` reescreve os transcripts antigos com tokens.
- **Saída grande:** acima de 50 KB, o Claude Code grava a saída completa ao lado do transcript.
	- O que o modelo lê dali sai mascarado; o arquivo, não.
- **Cópias reveladas:** o `pii-reveal` grava texto puro em `~/.cache/pii-tokens/reveal`, legível só por você.
	- São apagadas depois de 24 horas, quando uma sessão abre ou o `pii-reveal` roda.
- **O cofre** é cifrado, com a chave no keyring do sistema.
	- Isso protege disco roubado ou backup vazado, não um programa rodando como você.

## Rede e LGPD

- **Depois de instalado, o plugin não faz chamada de rede.** Máscara, cofre e tokens ficam na sua máquina. A instalação baixa `keyring` e `cryptography`, conferidas por hash.
- **O token é pseudônimo, não anônimo.** Ele é estável e liga os registros da mesma pessoa; para a LGPD, dado pseudonimizado continua sendo dado pessoal.
- **Não é certificado de conformidade com a LGPD.** Ele reduz o dado pessoal que sai para a API; o que é permitido mandar continua sendo decisão sua.
