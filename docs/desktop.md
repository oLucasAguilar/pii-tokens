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
- **Use no modo Claude** (o chat, ícone à esquerda do `</>`). No modo Code a extensão não chega à sessão; lá, quem protege é o plugin.
- Testado no Claude Desktop 4.29 para Windows, com o [Metabase](#metabase).

## Instalar

1. No repositório, rode `make desktop-bundle`. Sai o arquivo `build/pii-tokens.mcpb`.
2. Abra o arquivo no Claude Desktop (macOS ou Windows). O Desktop instala o Python e as dependências sozinho.
3. Preencha os campos e ative a extensão.

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

- **CPF, CNPJ, email e telefone:** em qualquer lugar do resultado, pelo formato.
- **Nome:** pela coluna, nos formatos de tabela que a extensão conhece (hoje, o do Metabase), venha de qualquer servidor.
- **Nome em JSON comum** (fora de uma tabela conhecida) passa.

## Login (OAuth)

- No primeiro uso abre o navegador.
- Depois disso, o login vale entre reinícios.
- O token fica cifrado no disco, com a chave no cofre do sistema.

## Desmascarar na consulta

Com `Unmask in queries` vazio (o padrão), um token que o Claude escreve numa consulta vai ao servidor como texto. Para seguir um registro, o Claude usa o ID.

Ligado, o Claude filtra pelo valor real sem lê-lo, mas uma consulta torta traz parte dele de volta.

- Nome nunca é desmascarado.

## Limites próprios do Desktop

Valem também os de [limits.md](limits.md). Além deles:

- **Coluna renomeada passa.** O nome é achado pela coluna, então `SELECT nome AS titulo` traz o nome sem máscara.
- **Resultado em formato desconhecido é retido**, não repassado: o Claude recebe um aviso no lugar.
- **Bloco que não é texto** (imagem, recurso embutido) também é retido.

## Metabase

Preset `metabase`. Testado com o Metabase 0.64 e 0.65.

- Libera o `execute_sql`, que lê mas não vem marcado (por isso o Desktop o lista em "Write/delete").
- Esconde o `visualize_query`, o `render_drill_through` e o `get_parameter_values`, cujos dados não passam pela máscara.
- O login pode pedir uma segunda tela na primeira consulta SQL.
- Medido: `SELECT nome AS titulo` passou 5 de 5. Para fechar, bloqueie o `execute_sql` e deixe o `execute_query`.
- Medido: com `Unmask in queries` ligado, `SUBSTRING('EMAIL#...', 1, n)` devolveu o começo do email.

Outro servidor ganha suas regras num módulo em `desktop/pii_proxy/upstreams/`.
