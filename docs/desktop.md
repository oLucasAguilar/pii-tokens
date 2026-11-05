# Claude Desktop

No chat do Claude Desktop, hook de plugin não roda. Por isso o plugin não protege o que um servidor MCP devolve ali.

Para esse caso existe uma extensão do Desktop: um servidor MCP local que fica entre o Claude e o servidor de verdade, e mascara o resultado antes de o Claude ler.

```
Claude Desktop ──> pii-tokens (no seu computador) ──> servidor MCP
                   mascara o que volta
```

- A máscara é a mesma do plugin, com o mesmo cofre e os mesmos tokens.
- Funciona com servidor MCP remoto (HTTP), com ou sem OAuth.
- **Protege só o que o servidor devolve.** O que você digita ou anexa no chat, e o que chega por outro conector, vai direto ao modelo.
- **Funciona no modo Claude** (o chat, ícone à esquerda do `</>`) e, no Desktop 4.4212, também no modo Code. No 4.29 ela não chegava ao modo Code.
- **Metabase no modo Code: use a extensão.** O plugin não lê o formato de tabela do Metabase, e o nome nas linhas passa.
- **Um servidor por extensão.** Outro servidor MCP ligado direto no Desktop passa sem máscara.
- **Trocou a configuração?** Feche e abra o Desktop: as conversas só veem as ferramentas novas depois disso.
- Testado no Claude Desktop 4.29 e 4.4212 para Windows, com o [Metabase](#metabase).

## Instalar

1. Baixe o `pii-tokens-<versão>.mcpb` da release mais recente com nome `desktop-v...`, em [Releases](https://github.com/oLucasAguilar/pii-tokens/releases). Não é o "Source code", que o GitHub põe em toda release.
2. Abra o arquivo no Claude Desktop (macOS ou Windows): duplo clique, ou Settings > Extensions > Advanced settings > Install Extension. O Desktop instala o Python e as dependências sozinho.
3. Preencha os campos e ative a extensão.

**Conferir o arquivo (opcional).** O pacote é código deste repositório, compactado. Para ver que o baixado é o mesmo código da release:

```
git clone https://github.com/oLucasAguilar/pii-tokens && cd pii-tokens
git checkout desktop-v<versão>
python3 desktop/build.py --check <caminho do .mcpb baixado>
# esperado: "same code as this folder"; senão, lista os arquivos diferentes
```

No Windows, `python` no lugar de `python3`. Para gerar o pacote você mesmo, sem baixar: `python3 desktop/build.py`, que grava `build/pii-tokens.mcpb`.

Não adicione o mesmo servidor também como conector direto: por ali o resultado chega ao Claude sem máscara.

## Campos

| Campo | Para quê |
|---|---|
| MCP server URL | O servidor que o Claude alcança pela extensão |
| Authentication | `oauth` abre a tela de login do servidor no navegador no primeiro uso. Vazio: sem login |
| Preset | Regras prontas para um servidor conhecido, como `metabase`. Vazio: as regras genéricas |
| Extra headers | JSON enviado em toda requisição ao host do servidor, para um proxy de autenticação na frente dele |
| Also allow / Block these tools | Nomes de ferramenta, separados por vírgula, para liberar ou bloquear |
| Unmask in queries | Tipos (`CPF`, `CNPJ`, `EMAIL`, `PHONE`) cujo token vira o valor real no que o Claude envia |

## Que ferramentas o Claude vê

- **Sem preset:** só as que o servidor marca como de leitura (`readOnlyHint`).
- **Com preset:** as regras daquele servidor, abaixo.
- **Bloquear vence liberar.** Ferramenta escondida também é recusada se o Claude chamar pelo nome.
- Resources e prompts do servidor não passam.

## O que é mascarado

- **CPF, CNPJ, email e telefone:** em qualquer lugar do resultado, pelo formato, inclusive no nome de um campo. Também no texto de apresentação que o servidor manda ao conectar e na descrição das ferramentas.
- **Nome:** pela coluna, nos formatos de tabela que a extensão conhece (a lista fica em `desktop/pii_proxy/upstreams/`), venha de qualquer servidor.
- **Nome em JSON comum** (fora de uma tabela conhecida) passa.
- **As opções do plugin** (as de `/plugin configure`) não valem na extensão.

## Login (OAuth)

- No primeiro uso abre o navegador.
- Depois disso, o login vale entre reinícios.
- O token fica cifrado no disco, com a chave no cofre do sistema.
- **Sair ou trocar de conta:** feche o Claude Desktop, apague a pasta `oauth` (`~/.local/share/pii-tokens/oauth`; no Windows, `%USERPROFILE%\.local\share\pii-tokens\oauth`) e abra de novo. O próximo uso abre a tela de login.

## Desmascarar na consulta

Com `Unmask in queries` vazio (o padrão), um token que o Claude escreve numa consulta vai ao servidor como texto. Para seguir um registro, o Claude usa o ID.

Ligado, o Claude filtra pelo valor real sem lê-lo, mas uma consulta torta traz parte dele de volta.

- Nome nunca é desmascarado.

## Limites próprios do Desktop

Valem também os de [limits.md](limits.md). Além deles:

- **CPF como número com casas decimais** (com `.0` no fim) passa, fora de uma coluna com nome de documento.
- **Servidor que redireciona de https para http** com `Extra headers` preenchido: a chamada falha, com o motivo, para o login não ir sem criptografia.
- **Valores fixos que uma ferramenta aceita** (a lista de opções de um parâmetro) passam sem máscara: a ferramenta precisa deles para ser chamada.
- **Coluna renomeada passa.** O nome é achado pela coluna, então `SELECT nome AS titulo` traz o nome sem máscara.
- **Resultado em formato desconhecido é retido**, não repassado: o Claude recebe um aviso no lugar.
- **Bloco que não é texto** (imagem, recurso embutido) também é retido.

## Metabase

Preset `metabase`. Testado com o Metabase 0.64 e 0.65.

- Libera o `execute_sql`, que lê mas não vem marcado (por isso o Desktop o lista em "Write/delete").
- Esconde o `visualize_query`, o `render_drill_through` e o `get_parameter_values`, cujos dados não passam pela máscara.
- O login pode pedir uma segunda tela na primeira consulta SQL.
- Medido em 01/11/2026: `SELECT nome AS titulo` passou 5 de 5. Para fechar, bloqueie o `execute_sql` e deixe o `execute_query`.
- Medido: com `Unmask in queries` ligado, `SUBSTRING('EMAIL#...', 1, n)` devolveu o começo do email.

Outro servidor ganha suas regras num módulo em `desktop/pii_proxy/upstreams/`.
