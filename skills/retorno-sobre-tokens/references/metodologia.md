# Metodologia

Este texto é o contrato de medição do ROT. O relatório repete a versão curta nas ressalvas.

## Período

Há quatro janelas, fechadas no instante em que o comando roda (ou em `--now`, para repetir uma conta):

| Opção | Duração |
| --- | --- |
| 24 horas | 1 dia |
| 7 dias | 7 dias |
| 15 dias | 15 dias |
| 30 dias | 30 dias |

Um evento entra se a data, com fuso, está em `[início, fim)`. Data sem fuso é ignorada e vira aviso. Não há fuso “implícito”.

## O que conta como produção

O ramo de produção é, nesta ordem: `--branch`, o campo `production_branch` do config, `origin/HEAD`, depois `main`, `master` ou `trunk`.

No histórico de primeiro pai desse ramo, entram:

- commits de merge (dois ou mais pais) — o que o merge trouxe em relação ao primeiro pai;
- commits cujo assunto é `Merge pull request #N` ou termina com `(#N)`, o padrão de squash do GitHub.

Commit direto no ramo, sem isso, não entra. Trabalho só numa branch que não foi mesclada não entra.

Se o GitHub CLI (`gh`) estiver autenticado no repositório, a lista de PRs mesclados na base completa o git. Isso recupera rebase-and-merge sem `(#N)` no assunto. O diff usado é o que está no ramo: do pai do primeiro commit daquele PR que é ancestral do resultado até o último. No squash, os commits originais não estão no ramo; o diff é o do commit espremido. Se o `gh` não responder, o relatório avisa e segue só com o git.

## Linha efetiva

Para cada arquivo de texto no diff (`git diff -M`, com detecção de rename):

```
linhas efetivas do arquivo = max(adições, remoções)
```

No período, soma-se arquivo por arquivo, PR por PR.

| Mudança | Adições | Remoções | Saldo | Efetivas |
| --- | ---: | ---: | ---: | ---: |
| Arquivo novo | 10 | 0 | +10 | 10 |
| Reescrita | 8 | 8 | 0 | 8 |
| Só remoção | 0 | 4 | −4 | 4 |
| Um arquivo +100 e outro −100 | 100 | 100 | 0 | 200 |

A reescrita conta uma vez. Não é churn (adições + remoções) e não é saldo (adições − remoções), que zeraria a refatoração. Arquivos independentes não se anulam: por isso o máximo é por arquivo, não no PR inteiro.

Rename puro, com diff 0/0, conta zero. Binário (numstat `-`) fica de fora, à parte.

O relatório também mostra adições, remoções e saldo, para a conta poder ser refeita.

### O que fica de fora pelo caminho

O primeiro motivo que casar ganha: lockfile, vendorizado, gerado, snapshot. A lista está em `scripts/rot_config.json`, chave `exclude`.

- Lockfile: o nome do arquivo (`package-lock.json`, `yarn.lock`, `Cargo.lock`, `go.sum` e os outros da lista).
- Vendorizado: segmento `vendor`, `third_party`, `third-party`, `node_modules` ou `external`.
- Gerado: segmento `dist`, `build`, `generated`, `__pycache__`, `.next`, `coverage`, ou sufixos como `.min.js`, `.generated.`, `_pb2.py`.
- Snapshot: pasta `__snapshots__`, sufixo `.snap` ou `.snapshot`.

`src/build.py` não é gerado: `build` precisa ser um segmento de pasta. `build/saida.js` é gerado.

Linha em branco e mudança só de formatação contam. O diff não ignora espaço.

## Tokens

A leitura é direta nos JSONL do Claude Code, em `~/.claude/projects` (ou `--projects-dir`). Não há um histórico paralelo. Cada arquivo `.jsonl` é uma sessão; subagentes em arquivos separados entram na conta, porque o token foi gasto.

Entra cada resposta de assistente com `usage` cuja data cai no período. Subagentes no mesmo árvore entram, porque o token foi gasto. Não guardamos o texto do prompt — só os números de PR citados, para a heurística abaixo.

Campos:

- `input_tokens`
- `output_tokens`
- `cache_read_input_tokens`
- gravação de cache: se existir o detalhe `cache_creation.ephemeral_5m_input_tokens` e `ephemeral_1h_input_tokens`, ele prevalece e o inteiro `cache_creation_input_tokens` não é somado de novo. Sem o detalhe, o inteiro inteiro é tratado como cache de 5 minutos.

Modelo desconhecido não recebe preço de outro modelo. Os tokens entram no volume e ficam fora do dólar, com aviso. `<synthetic>` tem preço zero de propósito.

Haiku 5.5: se entrada + gravações + leitura daquela resposta passam de 100.000, usa a faixa publicada acima de 100 mil tokens de prompt. No limite exato de 100.000, fica a faixa de até 100 mil.

### Atribuição a repositório e a PR

- Repositório: a pasta `cwd` da sessão, subida até a raiz git.
- PR: se o prompt cita `#N` ou `pull/N` de um PR que entrou em produção naquele repo, os tokens da sessão vão para ele. Se cita mais de um, reparte por igual.
- Senão, se o intervalo da sessão cruza a janela do PR (do primeiro commit da branch até o merge; no squash, a janela é o instante do commit), reparte entre os PRs que cruzam.
- O resto fica no repositório, sem PR.

O custo por linha do período usa todos os tokens lidos, não só os atribuídos. A linha “repositórios que publicaram” restringe aos tokens cujo `cwd` cai num repo que mesclou PR no período.

## Custo

Equivalente de API, em dólares por milhão de tokens:

```
entrada × preço de entrada
+ saída × preço de saída
+ cache de 5 min × preço de gravação de 5 min
+ cache de 1 h × preço de gravação de 1 h
+ leitura de cache × preço de leitura
```

A tabela embarcada foi conferida em 2026-10-23 em <https://platform.claude.com/docs/en/about-claude/pricing> e <https://claude.com/pricing>. É preço de lista global, não Bedrock regional, não lote, sem desconto. Edite `models` quando o preço mudar.

Assinatura proporcional:

```
mensalidade em USD × (dias do período / 30,4375)
30,4375 = 365,25 / 12
```

| Plano | Mensalidade usada | Fonte conferida em 2026-10-23 |
| --- | ---: | --- |
| API sob demanda | nenhuma; vale o equivalente de API | a mesma tabela de tokens |
| Claude Pro mensal | US$ 20 | <https://claude.com/pricing> |
| Claude Pro anual | US$ 200/12 | a mesma página (US$ 200 à vista; o site também fala em cerca de US$ 17/mês) |
| Claude Max 5x | US$ 100 | <https://support.claude.com/en/articles/11049741-what-is-the-max-plan> |
| Claude Max 20x | US$ 200 | a mesma página |

Trinta dias não são uma fatura cheia. No plano de assinatura, o indicador “custo por linha efetiva” usa o caixa proporcional. O equivalente de API aparece do lado, porque a assinatura não é medição por token. Na API sob demanda, o indicador usa o equivalente de API.

O real é `dólar × usd_brl`. A taxa que vem no config é a PTAX venda do Banco Central em 22/10/2026: 5,0383. Não há consulta ao vivo. `null`, `0` ou `--exchange-rate 0` desligam o real.

O plano não é lido de um arquivo de conta. Dá para fixá-lo com `--plan`, `ROT_PLAN` ou `default_plan`. Se existir `ANTHROPIC_API_KEY`, o prompt só avisa que a API sob demanda pode ser o caso — a chave não é impressa e a escolha não é automática.
