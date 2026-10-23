# Return on Tokens (ROT)

ROT mede, num período que você escolhe, quanto código chegou à produção e quanto isso custou em tokens do Claude Code. A moeda base é o dólar. O real entra por uma taxa de câmbio editável.

É uma skill de Claude Code e um comando de linha. Licença MIT, copyright Pierre Schurmann.

## O que é Return on Tokens (ROT)

Return on Tokens responde uma pergunta estreita: no intervalo analisado, quantas linhas efetivas foram parar no ramo de produção, quantos tokens o Claude Code gastou nesse intervalo e qual foi o custo — o equivalente de API, pela tabela publicada, e, se você tem assinatura, a mensalidade proporcional ao período.

Duas razões saem daí: custo por linha efetiva, e linhas efetivas por milhão de tokens.

O número descreve volume que entrou em produção e custo do uso medido. Ele não estima salário, hora economizada, receita nem risco. Essa conta de negócio fica de fora de propósito: ela depende de premissas que nenhum log contém.

## Como funciona

1. **Escolha do período.** O comando pergunta: qual período? 24 horas, 7 dias, 15 dias ou 30 dias. A janela fecha no instante da execução (ou num instante fixo, com `--now`, para repetir a mesma conta).

2. **Coleta dos pull requests que foram para produção.** Em cada repositório git, o ROT olha o ramo de produção (o padrão do remoto, ou `main` / `master` / `trunk`, ou o ramo que você indicar). Entra o que chegou lá por merge, ou por commit de squash cujo assunto termina em `(#N)` ou diz `Merge pull request #N`. Com o GitHub CLI autenticado, a lista de PRs mesclados completa o git — inclusive rebase sem número no assunto. Commit direto no ramo, e trabalho que ficou numa branch, ficam de fora.

3. **Cálculo das linhas efetivas, incluindo refatorações.** Em cada arquivo de texto do diff, com detecção de rename:

   ```
   linhas efetivas do arquivo = max(adições, remoções)
   ```

   A soma é arquivo por arquivo. Uma reescrita de 8 linhas por 8 conta 8: uma vez, em vez de 16 (adições + remoções) ou 0 (saldo). Um arquivo novo de 100 linhas e outro com 100 linhas removidas contam 200, porque são arquivos diferentes. O relatório também mostra adições, remoções e saldo. Lockfiles, código vendorizado, arquivo gerado e snapshot saem pelo caminho; as listas são editáveis.

4. **Leitura dos tokens dos logs do Claude Code.** O ROT lê os JSONL em `~/.claude/projects` (entrada, saída, gravação de cache de 5 minutos e de 1 hora, leitura de cache). Cada arquivo é uma sessão. Entra só o uso cuja data cai no período. A pasta da sessão liga o token a um repositório; a menção a `#N` ou a janela do PR tenta ligar a um PR. Essa ligação é heurística. O total do período é a medida firme.

5. **Identificação do plano e cálculo de custo.** O comando pergunta o plano, ou usa `--plan` / `ROT_PLAN` / `default_plan` no config. API sob demanda usa o preço de tabela dos tokens. Pro e Max usam a mensalidade proporcional: mensalidade × dias do período / 30,4375 (30,4375 = 365,25 / 12). Os dois custos aparecem. Na assinatura, o custo por linha usa o caixa proporcional; o equivalente de API fica ao lado. Se `ANTHROPIC_API_KEY` existir, o prompt só avisa — a chave não é lida nem impressa, e a escolha não é automática.

O real é `dólar × usd_brl`. A taxa que vem no config é a PTAX venda do Banco Central em 22/10/2026 (5,0383). Não há consulta ao vivo. Edite o número, ou passe `--exchange-rate`. Zero desliga o real.

## Como instalar

Requisitos: Python 3.11 ou superior, e `git`. O `gh` é opcional. Não há dependência de pacote.

Copie a skill para a pasta de skills do Claude Code:

```bash
mkdir -p ~/.claude/skills
cp -R skills/return-on-tokens ~/.claude/skills/return-on-tokens
```

Um link simbólico também serve, se você for editar o config neste repositório:

```bash
ln -s "$(pwd)/skills/return-on-tokens" ~/.claude/skills/return-on-tokens
```

Preços, mensalidades, câmbio, ramo de produção e listas de exclusão ficam em `skills/return-on-tokens/scripts/rot_config.json`. Vale a pena abrir esse arquivo uma vez e ajustar o que for diferente da sua fatura.

## Como usar

Na conversa do Claude Code, peça o ROT. A skill pergunta o período e o plano antes de medir.

No terminal, a partir da pasta da skill, ou com o caminho completo do script:

```bash
python3 ~/.claude/skills/return-on-tokens/scripts/rot_report.py
```

Num terminal interativo ele pergunta:

```
Qual período? 24 horas, 7 dias, 15 dias ou 30 dias
Qual plano ou licença você usa?
```

Com as respostas já na mão:

```bash
python3 scripts/rot_report.py --period 7d --plan max-5x
python3 scripts/rot_report.py --period 24h --plan api --repo ~/projetos/app
python3 scripts/rot_report.py --period 30d --plan custom --monthly-usd 20 --plan-label "Outra ferramenta"
```

Períodos: `24h`, `7d`, `15d`, `30d`. Planos: `api`, `pro-monthly`, `pro-annual`, `max-5x`, `max-20x`, `custom`.

`--repo` pode repetir. Sem ele, entram o repositório do diretório atual e os repositórios que aparecerem nos logs do período. `--json` imprime a mesma conta com chaves em inglês, para outro programa ler. O texto normal sai em português.

Os testes desta pasta recriam um repositório git com PRs mesclados e logs JSONL de sessão:

```bash
python3 tests/test_rot.py
```

## Metodologia e limitações

O texto completo, com a tabela de preços e a fórmula, está em `skills/return-on-tokens/references/metodologia.md`. O resumo:

**Produção.** Diff do que entrou no ramo de produção. Merge: primeiro pai até o commit do merge. Squash: o próprio commit. Rebase sem `(#N)` só entra se o `gh` listar o PR e os commits estiverem neste clone.

**Linha efetiva.** `max(adições, remoções)` por arquivo, somado. Rename puro (diff 0/0) conta zero. Binário fica de fora. Linha em branco e mudança só de formatação contam.

**Fora da conta, pelo caminho.** Lockfiles (`package-lock.json`, `yarn.lock`, `Cargo.lock`, `go.sum` e o resto da lista), pastas `vendor` / `third_party` / `node_modules` / `external`, gerados (`dist`, `build`, `generated`, `.min.js`, `.generated.` e outros) e snapshots (`__snapshots__`, `.snap`). `src/build.py` continua na conta: `build` precisa ser uma pasta. Um gerado com nome fora da lista entra. Edite `exclude` no config.

**Tokens.** Só os JSONL locais do Claude Code nesta máquina. Conversa na web, outro aplicativo e log apagado não aparecem. Data sem fuso é ignorada e vira aviso. Se o detalhe de cache de 5 minutos e de 1 hora existir, ele prevalece e o total inteiro não é somado de novo. Sem o detalhe, a gravação é cobrada como 5 minutos.

**Preço.** Dólares por milhão de tokens, preço de lista global da API, conferido em 2026-10-23 em [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) e [claude.com/pricing](https://claude.com/pricing). Modelo sem linha na tabela não ganha preço emprestado: os tokens entram no volume e ficam fora do dólar, com aviso. Haiku 5.5 muda de faixa acima de 100 mil tokens de prompt naquela resposta.

**Assinatura.** Pro mensal US$ 20. Pro anual US$ 200 por ano, rateado como 200/12. Max 5x US$ 100 por mês. Max 20x US$ 200 por mês. Fontes no config, conferidas em 2026-10-23. Trinta dias não são uma fatura cheia. O custo proporcional é um fixo rateado no período: quanto mais linha entra em produção, menor fica o custo por linha. Ele não é a causa das linhas.

**Câmbio.** PTAX venda de 22/10/2026, R$ 5,0383 por dólar, campo `usd_brl`. O dólar segue sendo a base.

**Atribuição por PR.** Pasta da sessão, número citado no prompt, ou cruzamento com a janela do PR. Se mais de um PR casa, o token da sessão é repartido por igual. Squash tem janela de um instante, então a menção ao número pesa mais.

**O que esta versão deixa de medir.** Quem escreveu a linha (pessoa ou modelo). Uso fora dos logs locais. Desconto, lote, Bedrock regional e imposto. Salário, hora economizada e resultado de negócio.

## Exemplo de saída

Fixture `sample-app`, 7 dias terminando em 23/10/2026 15:00 UTC, Claude Max 5x, câmbio 5,0383. O PR #1 reescreve código e traz lockfile, vendor, gerado e snapshot (esses ficam fora). O PR #2 é um squash de 5 linhas. Um commit direto no `main` não entra. A mesma saída está em `skills/return-on-tokens/examples/exemplo-relatorio.txt`.

```
========================================================================
  ROT — Return on Tokens
  7 dias · 16/10/2026 15:00 UTC → 23/10/2026 15:00 UTC
  Plano: Claude Max 5x · US$ 100,00/mês
========================================================================

TOKENS
  Logs em ~/.claude/projects
  Entrada                              1.020.000
  Saída                                  102.000
  Gravação de cache (5 min)              200.000
  Gravação de cache (1 h)                      0
  Leitura de cache                     1.000.000
  Total                                2.322.000
  Sessões no período                           2

CÓDIGO EM PRODUÇÃO
  sample-app · ramo main · fonte: git
    PR #1        80036a9  23 linhas efetivas  (+19 −13, saldo +6)
      Merge pull request #1 from dev/feature
    PR #2        6770e46  5 linhas efetivas  (+5 −0, saldo +5)
      Adiciona healthcheck (#2)

  Linhas efetivas                             28
  Adições                                     24
  Remoções                                    13
  Saldo                                      +11
  Fora da conta (adições + remoções): 100 em lockfiles, 50 em código vendorizado, 62 em arquivos gerados, 20 em snapshots.

CUSTO
  Equivalente de API                        US$ 5,58
  Assinatura proporcional                  US$ 23,00
    US$ 100,00 × 7/30,4375 dias
  Custo usado nos indicadores              US$ 23,00
    Caixa da assinatura neste período, não o preço de tabela da API.
  Em reais                                 R$ 115,87
    US$ 1 = R$ 5,0383. Câmbio editável em rot_config.json.
    Equivalente de API em reais: R$ 28,11.

INDICADORES
  Custo por linha efetiva                             US$ 0,8214
  O mesmo em reais                                    R$ 4,14
  Equivalente de API por linha efetiva                US$ 0,1993
  Linhas efetivas por milhão de tokens                12,06
  Idem, só repositórios que publicaram                12,06

POR REPOSITÓRIO
  sample-app: 28 linhas efetivas, 2.322.000 tokens na pasta, API US$ 5,58

RESSALVAS
  - Linha efetiva é, por arquivo de texto, o maior valor entre adições e remoções. Uma refatoração que troca 100 linhas por 100 conta 100 — não 200 e não zero. Arquivos diferentes não se cancelam.
  - Entram mudanças que chegaram ao ramo de produção por commit de merge ou por assunto de pull request (Merge pull request #N ou sufixo (#N)). Commit direto, sem PR, fica de fora. Rebase sem número no assunto só entra se o GitHub CLI informar o PR.
  - Lockfile, código vendorizado, arquivo gerado e snapshot saem da conta pelo caminho. Um gerado com nome fora da lista entra. As listas estão em rot_config.json.
  - Os tokens vêm só dos JSONL locais do Claude Code nesta máquina. Conversa na web, outro aplicativo e log apagado não aparecem.
  - O custo da assinatura é a mensalidade proporcional ao período (mês de 30,4375 dias, que é 365,25/12). É um custo fixo rateado, não a causa das linhas: quanto mais código entra em produção, menor fica o custo por linha.
  - O equivalente de API usa a tabela publicada e editável. Modelo sem linha não entra no dólar e aparece nos avisos. Gravação de cache sem o detalhe de 5 minutos ou 1 hora é cobrada como 5 minutos.
  - Atribuição de token a um PR é heurística (pasta da sessão, menção ao número, janela do PR). O total do período é a medida firme.
  - Isto não é ROI de negócio. Não estima salário, hora economizada, receita nem risco.
  - O real usa a taxa editável de 5,0383 reais por dólar (2026-10-22). Não é cotação ao vivo. O dólar continua sendo a moeda base.
========================================================================
```
