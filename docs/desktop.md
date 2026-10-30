# Claude Desktop

No chat do Claude Desktop, hook de plugin não roda. Por isso o plugin não protege o que um servidor MCP devolve ali.

Para esse caso existe uma extensão do Desktop: um servidor MCP local que fica entre o Claude e o servidor de verdade, e mascara o resultado antes de o Claude ler.

```
Claude Desktop ──> pii-tokens (no seu computador) ──> servidor MCP (Metabase, por exemplo)
                   mascara o que volta
```

- A máscara é a mesma do plugin, com o mesmo cofre e os mesmos tokens.
- Funciona com servidor MCP remoto (HTTP), com ou sem OAuth.
- **Ainda não testado no Claude Desktop.** Testado contra o Metabase real, rodando o pacote como o Desktop roda, no Linux.

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
| Preset | Regras de ferramenta para um servidor conhecido. Hoje há `metabase` |
| Extra headers | JSON enviado em toda requisição, login incluído. Serve para um proxy de autenticação na frente do servidor, como o token de serviço do Cloudflare Access |
| Also allow / Block these tools | Nomes de ferramenta, separados por vírgula, para liberar ou bloquear |
| Unmask in queries | Tipos (`CPF`, `CNPJ`, `EMAIL`, `PHONE`) cujo token vira o valor real no que o Claude envia |

## Que ferramentas o Claude vê

- **Sem preset:** só as que o servidor marca como de leitura (`readOnlyHint`).
- **Preset `metabase`:**
	- libera o `execute_sql`, que lê mas não vem marcado;
	- esconde o `visualize_query` e o `render_drill_through`, cujo gráfico busca as linhas direto do Metabase, fora da extensão;
	- esconde o `get_parameter_values`, que devolve valores de coluna sem a coluna para mascarar.
- **Bloquear vence liberar.** Ferramenta escondida também é recusada se o Claude chamar pelo nome.
- Resources e prompts do servidor não passam.

## Login (OAuth)

- No primeiro uso abre o navegador. O Metabase pode pedir uma segunda tela na primeira consulta SQL, porque o escopo de SQL é pedido na hora em que é preciso.
- Depois disso, o login vale entre reinícios.
- O token fica cifrado no disco, com a chave no cofre do sistema. Só o cofre não serviria: o Windows recusa valores acima de 2560 bytes.

## Desmascarar na consulta

Com `Unmask in queries` vazio (o padrão), um token que o Claude escreve numa consulta vai ao servidor como texto. Para seguir um registro, o Claude usa o ID.

Ligado, o Claude filtra pelo valor real sem lê-lo, mas uma consulta torta traz parte dele de volta.

- Medido no Metabase: `SUBSTRING('EMAIL#...', 1, n)` devolveu o começo do email.
- Nome nunca é desmascarado. Ele não é reconhecido pelo formato na volta, então voltaria sem máscara.

## Limites próprios do Desktop

Valem também os de [limits.md](limits.md). Além deles:

- **Coluna renomeada no SQL passa.** `SELECT nome AS titulo` traz o nome sem máscara, porque a coluna é reconhecida pelo nome. No Metabase, medido: 5 de 5. Para fechar, bloqueie o `execute_sql` e deixe o `execute_query`.
- **O que você digita no chat não é mascarado.** Sem hook, o prompt vai direto ao modelo.
- **Resultado em formato desconhecido é retido**, não repassado: o Claude recebe um aviso no lugar.
- **Bloco que não é texto** (imagem, recurso embutido) também é retido.
