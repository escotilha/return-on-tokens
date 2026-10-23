# Metodologia

Este texto é o contrato de medição do ROT. O relatório repete a versão curta na seção RESSALVAS.

## Período

Há quatro janelas. Elas fecham no instante em que o comando roda, ou em `--now`, para repetir uma conta:

| Opção | Duração |
| --- | --- |
| 24 horas | 1 dia |
| 7 dias | 7 dias |
| 15 dias | 15 dias |
| 30 dias | 30 dias |

Um evento entra se a data dele, com fuso, estiver em `[início, fim)`. Uma data sem fuso é ignorada e vira aviso: não existe fuso "implícito".

No modo equipe, o período é fixado por quem abre a rodada e gravado em `rodada.json`. Todos os devs medem exatamente o mesmo intervalo, mesmo que rodem o comando dias depois.

## O que conta como produção

O ramo de produção é o primeiro desta lista que existir:

1. `--branch`;
2. o campo `production_branch` do config;
3. `origin/HEAD`;
4. `main`, `master` ou `trunk`.

No histórico de primeiro pai desse ramo, entram:

- commits de merge (com dois ou mais pais), com o que o merge trouxe em relação ao primeiro pai;
- commits cujo assunto é `Merge pull request #N` ou termina com `(#N)`, que é o padrão de squash do GitHub.

Não entram commits diretos no ramo nem trabalho que ficou numa branch sem merge.

Com o GitHub CLI (`gh`) autenticado, a lista de PRs mesclados completa o git. Isso recupera rebases sem `(#N)` no assunto. Se o `gh` não responder, o relatório avisa e segue só com o git.

## Só os PRs de quem está medindo

Antes de somar linhas, o ROT decide quem é "você". A primeira fonte que responder ganha:

1. `--autor` na linha de comando. Pode ser repetido e aceita login ou e-mail.
2. O bloco `autores` do config (`logins` e `emails`).
3. O login do GitHub, por `gh api user`.
4. O `git config user.email` de cada repositório e o global.

Para cada PR:

- Se o `gh` informou o autor do PR e há login conhecido, quem decide é o login.
- Senão, decide o e-mail do autor do primeiro commit do PR. No squash, vale o autor do próprio commit. Um e-mail `NNN+login@users.noreply.github.com` casa com o login.

PRs de outras pessoas ficam fora da conta. O relatório mostra quantos foram, quantas linhas efetivas tinham e quantos autores diferentes havia. Se o ROT não conseguir descobrir nenhuma identidade, nenhum PR conta e o relatório avisa com destaque. É melhor zero que o código da equipe inteira atribuído a uma pessoa.

Com `--so-com-sessao`, um PR só conta se houver uma sessão do Claude Code no mesmo repositório que cruze a janela do PR, estendida 2 dias para trás. A extensão existe porque um squash tem janela de um instante só, e o trabalho acontece antes dele. Os PRs descartados por esse filtro aparecem como contagem.

## Linha efetiva

Para cada arquivo de texto no diff (`git diff -M`, com detecção de rename):

```
linhas efetivas do arquivo = max(adições, remoções)
```

No período, a soma é feita arquivo por arquivo e PR por PR.

| Mudança | Adições | Remoções | Saldo | Efetivas |
| --- | ---: | ---: | ---: | ---: |
| Arquivo novo | 10 | 0 | +10 | 10 |
| Reescrita | 8 | 8 | 0 | 8 |
| Só remoção | 0 | 4 | −4 | 4 |
| Um arquivo +100 e outro −100 | 100 | 100 | 0 | 200 |

A reescrita conta uma vez. A métrica não é churn (adições + remoções), nem saldo (adições − remoções), que zeraria a refatoração. Arquivos independentes não se anulam, e é por isso que o máximo é calculado por arquivo, não no PR inteiro.

Um rename puro, com diff 0/0, conta zero. Um arquivo binário fica de fora. O relatório também mostra adições, remoções e saldo, para que a conta possa ser refeita.

### O que fica de fora pelo caminho

O primeiro motivo que casar ganha, nesta ordem: lockfile, vendorizado, gerado, snapshot. As listas estão em `scripts/rot_config.json`, na chave `exclude`.

- **Lockfile:** pelo nome do arquivo (`package-lock.json`, `yarn.lock`, `Cargo.lock`, `go.sum` e os outros da lista).
- **Vendorizado:** segmento de pasta `vendor`, `third_party`, `third-party`, `node_modules` ou `external`.
- **Gerado:** segmento de pasta `dist`, `build`, `generated`, `__pycache__`, `.next` ou `coverage`, ou sufixos como `.min.js`, `.generated.` e `_pb2.py`.
- **Snapshot:** pasta `__snapshots__`, ou sufixo `.snap` ou `.snapshot`.

`src/build.py` não é gerado, porque `build` precisa ser um segmento de pasta. Já `build/saida.js` é gerado. Linhas em branco e mudanças só de formatação contam: o diff não ignora espaço.

## Tokens

### De onde vêm

Dos JSONL do Claude Code em `~/.claude/projects`, ou na pasta de `--projects-dir`. Entra cada resposta de assistente com `usage` cuja data cai no período, incluindo as de subagentes, porque esses tokens também foram gastos. O texto dos prompts não é guardado: só os números de PR citados, que servem para a atribuição.

Campos lidos:

- `input_tokens`: entrada;
- `output_tokens`: saída;
- `cache_read_input_tokens`: leitura de cache;
- gravação de cache: se existir o detalhe `cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`, ele prevalece. Sem o detalhe, o total `cache_creation_input_tokens` é tratado como gravação de 5 minutos.

### Sem duplicatas

O Claude Code grava a mesma resposta mais de uma vez:

- **Streaming:** um registro por bloco de conteúdo, todos com o mesmo uso, ou com o uso crescendo até o valor final.
- **Sessão retomada:** o arquivo novo repete as respostas da sessão antiga.
- **Subagentes e cópias:** o mesmo arquivo pode aparecer em mais de uma pasta.

Somar tudo infla o custo em mais de duas vezes. A regra do ROT é:

1. Um arquivo com conteúdo idêntico (mesmo sha256) a outro já lido é pulado inteiro.
2. Cada resposta é identificada pela dupla `message.id` + `requestId`. Quando falta um dos dois, vale o `uuid` do registro. A identificação vale para todos os arquivos e sessões, não só dentro de um arquivo.
3. Entre os registros repetidos, cada campo de uso fica com o maior valor visto, que é o uso final. A data é a do primeiro registro, e a resposta pertence à sessão em que apareceu primeiro.
4. O filtro de período é aplicado depois da deduplicação.
5. Um registro sem nenhum identificador conta como único.

O relatório mostra quantos registros repetidos e quantos arquivos idênticos foram descartados.

### Atribuição a repositório e a PR

- **Repositório:** a pasta `cwd` da sessão, subindo até a raiz do git.
- **PR, pela menção:** se o prompt cita `#N` ou `pull/N` de um PR que entrou em produção naquele repositório, os tokens da sessão vão para ele. Se cita mais de um, o rateio é por igual.
- **PR, pela janela:** sem menção, a sessão é rateada entre os PRs cuja janela ela cruza. A janela vai do primeiro commit da branch até o merge; no squash, é o instante do commit.
- **Resto:** o que não casar fica no repositório, sem PR.

Essa atribuição é heurística. O custo do período usa todos os tokens lidos, e não só os atribuídos.

## Preço

O equivalente de API, em dólares por milhão de tokens, é:

```
entrada × preço de entrada
+ saída × preço de saída
+ cache de 5 min × preço de gravação de 5 min
+ cache de 1 h × preço de gravação de 1 h
+ leitura de cache × preço de leitura
```

A tabela embarcada foi conferida em 2026-10-23 em <https://platform.claude.com/docs/en/about-claude/pricing> e <https://claude.com/pricing>. É o preço de lista global, sem Bedrock regional, sem lote e sem desconto. Edite `models` quando o preço mudar.

### Casamento exato

O nome do modelo no log ganha preço só por um destes caminhos, nesta ordem:

1. Existe uma linha com o nome exato em `models`.
2. Existe um apelido exato em `model_aliases` que aponta para uma linha existente. Exemplo: `"claude-opus-4-6[1m]": "claude-opus-4-6"`.
3. O nome termina em `-AAAAMMDD` (8 dígitos começando por 20) e o nome sem esse sufixo existe na tabela. Assim, `claude-haiku-4-5-20251001` usa `claude-haiku-4-5`.

Não existe casamento por prefixo. Antes, `claude-opus-4-6[1m]` ou `claude-sonnet-5-5-preview` herdavam o preço de outra linha. Agora ficam **sem preço**:

- os tokens aparecem no relatório numa linha própria, "Sem preço (fora do custo)";
- eles não entram no dólar;
- o relatório avisa com destaque que o equivalente de API está subestimado.

`<synthetic>` tem preço zero de propósito.

No Haiku 5.5, se entrada + gravações + leitura daquela resposta passam de 100.000 tokens, vale a faixa publicada acima de 100 mil tokens de prompt. No limite exato de 100.000, vale a faixa de até 100 mil.

### Tokens por tipo

O relatório mostra cada tipo de token (entrada, saída, gravação de 5 min, gravação de 1 h, leitura de cache) com o seu custo de API e a sua fatia do custo total. Isso substitui o antigo "linhas efetivas por milhão de tokens". Aquele número era dominado pela leitura de cache, que cresce com o tamanho do contexto e não com o código produzido, e por isso enganava.

## Custo

A assinatura proporcional é:

```
mensalidade em USD × (dias do período / 30,4375)
30,4375 = 365,25 / 12
```

| Plano | Mensalidade usada | Fonte conferida em 2026-10-23 |
| --- | ---: | --- |
| API sob demanda | nenhuma; vale o equivalente de API | a mesma tabela de tokens |
| Claude Pro mensal | US$ 20 | <https://claude.com/pricing> |
| Claude Pro anual | US$ 200/12 | a mesma página |
| Claude Max 5x | US$ 100 | <https://support.claude.com/en/articles/11049741-what-is-the-max-plan> |
| Claude Max 20x | US$ 200 | a mesma página |

Na assinatura, o indicador "custo por linha efetiva" usa o caixa proporcional, e o equivalente de API aparece ao lado. Na API sob demanda, o indicador usa o equivalente de API.

O real é `dólar × usd_brl`. A taxa do config é a PTAX venda do Banco Central de 22/10/2026: 5,0383. Não há consulta ao vivo. `null`, `0` ou `--exchange-rate 0` desligam o real.

O plano não é lido de nenhum arquivo de conta. Ele vem de `--plan`, `ROT_PLAN`, `default_plan` ou, no modo equipe, do plano padrão da rodada.

## Indicadores

- **Custo por linha efetiva:** o custo usado (assinatura proporcional ou API) dividido pelas linhas efetivas.
- **Equivalente de API por linha efetiva:** o mesmo, pela tabela de API.
- **Linhas efetivas por milhão de tokens de SAÍDA:** uma razão de volume, opcional. Ela usa só a saída, porque entrada e cache dependem do contexto. Não mede qualidade.

## Modo equipe

### Arquivos no repositório central

```
<rodada>/rodada.json     período fixo, devs esperados, plano padrão, repositório e ramo
<rodada>/README.md       instruções para o dev, com o comando de envio
<rodada>/<login>.json    um por dev
<rodada>/resumo.md       opcional, gravado ao fechar
```

### O que um envio contém

Cada `<login>.json` traz:

- `schema_version`, `tool_version`, `rodada`, `login`, `generated_at` e o período;
- o plano;
- os tokens por tipo, com custo por tipo, tokens sem preço por modelo e tokens por modelo;
- o custo;
- as linhas (efetivas, adições, remoções, saldo);
- a lista de PRs: chave, repositório (nome curto ou `dono/repo`), número, título, URL, data do merge e linhas;
- a contagem de PRs de outros autores excluídos;
- o número de sessões e as estatísticas de duplicatas.

Um envio **não** contém prompts, texto de conversa, caminhos locais nem e-mails.

### Como o total é calculado

- **Tokens e custo:** somados entre os devs. Cada dev usa o próprio plano.
- **PRs:** deduplicados pela chave (a URL do PR; sem URL, `dono/repo#N`). Um PR enviado por duas pessoas conta uma vez nas linhas do total. Na linha de cada dev, ele aparece para os dois.
- **Custo por linha da equipe:** custo total dividido pelas linhas efetivas dos PRs únicos.
- **Período diferente:** um envio com início ou fim diferente do da rodada é sinalizado em AVISOS.
- **Faltas:** quem está na lista e não enviou aparece como "não enviou". Ao fechar, o comando pergunta se gera o total assim mesmo; `--gerar-mesmo-assim` pula a pergunta.

O git é usado com as credenciais de quem roda o comando. O clone fica em `~/.cache/rot-equipe/` (ou em `--cache-dir` / `equipe.pasta_cache`). Uma pasta comum também serve como repositório central: nesse caso, os arquivos são escritos direto nela.

## Limitações

- **Linha não é valor.** Uma correção crítica e um boilerplate pesam o mesmo.
- **Volume de token não é produtividade.** A leitura de cache domina o volume e cresce com o contexto. Por isso o ROT mostra os tipos separados e não faz manchete com o total.
- **Só uma máquina.** O ROT lê os logs locais. Conversa na web, outro computador e log apagado não aparecem.
- **Autoria por e-mail.** Sem `gh`, a autoria depende do e-mail do commit. Se você usa mais de um, liste todos em `autores.emails`. Pareamento e coautoria (`Co-authored-by`) não são considerados.
- **Modelo novo fica sem preço** até alguém editar a tabela. O custo de API fica subestimado enquanto isso, com aviso.
- **A atribuição a PR é heurística.** O total do período é a medida firme.
- **Fora do escopo:** quem escreveu cada linha (pessoa ou modelo), descontos, lote, Bedrock, impostos, salário, hora economizada e resultado de negócio.
