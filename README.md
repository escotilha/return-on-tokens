# Retorno sobre Tokens (ROT)

O ROT responde uma pergunta simples: neste período, quanto código **seu** chegou à produção, e quanto custaram os tokens do Claude Code que você usou para isso?

Funciona sozinho, na sua máquina, ou em equipe: o CTO abre uma rodada, cada dev envia os próprios números, e o CTO fecha com o total da equipe e uma linha por pessoa.

É uma skill de Claude Code com um script em Python, sem dependências. Licença MIT, copyright Pierre Schurmann.

## O que é Retorno sobre Tokens (ROT)

Num período fixo (24 horas, 7 dias, 15 dias ou 30 dias), o ROT junta duas medidas:

- **Linhas efetivas que foram para produção.** São as linhas dos pull requests de sua autoria que entraram no ramo de produção. Por arquivo, conta o maior valor entre adições e remoções. Assim, uma refatoração que troca 8 linhas por 8 conta 8 (e não 16, nem zero).
- **Tokens e custo.** Vêm dos logs locais do Claude Code, separados em entrada, saída, gravação de cache e leitura de cache, cada um com o seu preço. O custo aparece de dois jeitos:
  - o equivalente de API, pela tabela publicada;
  - se você assina Pro ou Max, a mensalidade rateada no período.

Daí sai o indicador principal: **custo por linha efetiva**. A moeda base é o dólar. O real aparece por uma taxa de câmbio que você pode editar.

O ROT não é ROI de negócio. Ele não estima salário, hora economizada, receita nem risco: nada disso está nos logs.

## Como funciona

1. **Período.** Você escolhe a janela. Ela fecha no instante em que o comando roda, ou no instante fixado por `--now`, que serve para repetir a mesma conta.

2. **PRs que foram para produção.** Em cada repositório, o ROT lê o histórico do ramo de produção (`main`, `master`, `trunk` ou o que você indicar). Entram:
   - merges;
   - squashes com `(#N)` no fim do assunto;
   - commits com o assunto `Merge pull request #N`.

   Com o GitHub CLI (`gh`) autenticado, a lista de PRs mesclados completa o git. Commit direto no ramo não entra.

3. **Só os seus PRs.** O ROT descobre quem é você por `gh api user` (login do GitHub) e `git config user.email`. Também aceita `--autor` ou o bloco `autores` do config. Os PRs de colegas mesclados no mesmo ramo ficam fora da conta, e o relatório diz quantos foram e quantas linhas tinham. Se o ROT não souber quem é você, nenhum PR conta e ele avisa em voz alta.

4. **Linhas efetivas.** Em cada arquivo do diff, conta `max(adições, remoções)`, e os arquivos são somados. Lockfiles, código vendorizado, arquivos gerados e snapshots saem da conta pelo caminho do arquivo.

5. **Tokens, sem duplicata.** O ROT lê os JSONL de `~/.claude/projects`. O Claude Code grava a mesma resposta mais de uma vez: uma por bloco durante o streaming, outra quando a sessão é retomada, e cópias nos arquivos de subagente. Sem cuidado, isso pode inflar o custo em mais de duas vezes. Por isso, cada resposta conta uma vez só, identificada pela dupla `message.id` + `requestId`, com o maior uso registrado. Arquivos idênticos em pastas diferentes também contam uma vez. O relatório mostra quantas duplicatas descartou.

6. **Preço só para modelo conhecido.** Um modelo só ganha preço pelo nome exato que está na tabela. Há duas exceções conservadoras:
   - um apelido que você declara em `model_aliases`;
   - o sufixo de data `-AAAAMMDD`, que é ignorado só quando o nome base existe na tabela.

   Não há palpite por prefixo. Um modelo fora da tabela aparece como **sem preço**: os tokens dele são listados à parte, ficam fora do custo, e o relatório avisa que o equivalente de API está subestimado.

7. **Plano e custo.** Na API sob demanda, o custo é o preço dos tokens. No Pro ou no Max, o custo usado no indicador é `mensalidade × dias / 30,4375`, e o equivalente de API aparece ao lado. O câmbio padrão é a PTAX venda do Banco Central de 22/10/2026 (R$ 5,0383).

## Como instalar

Você precisa de Python 3.11 ou mais novo e de `git`. O `gh` é opcional, mas recomendado: ele informa o seu login e o autor de cada PR.

```bash
mkdir -p ~/.claude/skills
cp -R skills/retorno-sobre-tokens ~/.claude/skills/retorno-sobre-tokens
```

Se você for editar o config neste repositório, um link simbólico também serve:

```bash
ln -s "$(pwd)/skills/retorno-sobre-tokens" ~/.claude/skills/retorno-sobre-tokens
```

Preços, mensalidades, câmbio, apelidos de modelo, autores, ramo de produção, listas de exclusão e o bloco `equipe` ficam em `skills/retorno-sobre-tokens/scripts/rot_config.json`. Vale abrir esse arquivo uma vez e conferir.

## Como usar

O jeito mais fácil é pedir ao Claude Code: "quero ver o meu ROT". A skill pergunta antes se você vai medir sozinho, enviar para uma rodada da equipe ou consolidar a equipe. Abaixo estão os três caminhos pelo terminal.

### Sozinho (só você)

1. Rode o comando:

   ```bash
   python3 ~/.claude/skills/retorno-sobre-tokens/scripts/rot_report.py
   ```

2. Responda as duas perguntas:

   ```
   Qual período? 24 horas, 7 dias, 15 dias ou 30 dias
   Qual plano ou licença você usa?
   ```

3. Leia o relatório: tokens por tipo, PRs, custo e indicadores.

Se você já sabe as respostas, passe tudo direto:

```bash
python3 scripts/rot_report.py --period 7d --plan max-5x
python3 scripts/rot_report.py --period 24h --plan api --repo ~/projetos/app
python3 scripts/rot_report.py --period 30d --plan custom --monthly-usd 20 --plan-label "Outra ferramenta"
python3 scripts/rot_report.py --period 7d --plan api --autor meu-login --autor eu@empresa.com
```

Opções:

- Períodos: `24h`, `7d`, `15d`, `30d`.
- Planos: `api`, `pro-monthly`, `pro-annual`, `max-5x`, `max-20x`, `custom`.
- `--repo` pode ser repetido. Sem ele, entram o repositório da pasta atual e os que aparecem nos logs do período.
- `--so-com-sessao` conta só os PRs que tiveram uma sessão do Claude Code no mesmo repositório durante a janela do PR, ou até 2 dias antes.
- `--json` imprime a mesma conta com chaves em inglês, para outro programa ler.

### Modo equipe

O modo equipe usa um **repositório git central**, privado, ao qual todos da equipe têm acesso de escrita. Cada rodada vira uma pasta nesse repositório:

- `rodada.json`: o período fixo, a lista de devs e o plano padrão;
- `README.md`: as instruções para os devs;
- um `<login>.json` para cada dev que enviou;
- `resumo.md`, opcional, com o total.

Ninguém envia prompt, texto de conversa nem caminho de pasta: só números, títulos e links dos PRs. Cada push usa as credenciais git de quem está rodando. Uma pasta local (ou compartilhada) também serve como repositório central, o que é útil para testar.

#### Para o CTO (ou quem administra)

1. **Uma vez só:** crie o repositório central vazio. Por exemplo, `sua-org/rot-equipe`, privado, com acesso de escrita para os devs. Se quiser, preencha em `rot_config.json`:

   ```json
   "equipe": {
     "repositorio_central": "git@github.com:sua-org/rot-equipe.git",
     "devs": ["login-1", "login-2", "login-3"]
   }
   ```

2. **Abra a rodada.** O período fica fixo a partir daqui:

   ```bash
   python3 ~/.claude/skills/retorno-sobre-tokens/scripts/rot_report.py abrir-rodada --periodo 7d \
     --repo-central git@github.com:sua-org/rot-equipe.git --devs login-1,login-2,login-3 --plano-padrao max-5x
   ```

   O comando grava `rodada.json` e `README.md` na pasta da rodada (por exemplo `2026-10-23_7d/`), faz o push e imprime o link do README no GitHub.

3. **Mande o link para a equipe.** O README explica o que fazer e traz um único comando para copiar e colar.

4. **Feche a rodada** quando os envios chegarem:

   ```bash
   python3 ~/.claude/skills/retorno-sobre-tokens/scripts/rot_report.py fechar-rodada --rodada 2026-10-23_7d \
     --repo-central git@github.com:sua-org/rot-equipe.git
   ```

   O comando atualiza o clone e mostra quem enviou e quem falta. Se faltar alguém, ele pergunta:

   ```
   Faltam login-2 e login-3. Gerar o total assim mesmo (s) ou esperar (n)?
   ```

   - `--gerar-mesmo-assim` pula a pergunta.
   - `--gravar-resumo` grava `resumo.md` na pasta da rodada.
   - `equipe` é outro nome para o mesmo comando.

5. **Leia o resultado.** Primeiro vem o **TOTAL DA EQUIPE**; depois, uma linha por dev, com linhas efetivas, PRs, tokens por tipo, custo, custo por linha e tokens sem preço. Um PR enviado por duas pessoas conta uma vez no total. Um envio com período diferente do da rodada aparece em destaque.

#### Para o dev

1. Abra o link que o CTO mandou e copie o comando, que tem esta forma:

   ```bash
   python3 ~/.claude/skills/retorno-sobre-tokens/scripts/rot_report.py enviar --rodada 2026-10-23_7d \
     --repo-central git@github.com:sua-org/rot-equipe.git
   ```

   Outra opção é pedir ao Claude Code: "roda o ROT da rodada 2026-10-23_7d". O link do README também serve no lugar do id: `--rodada https://github.com/sua-org/rot-equipe/blob/main/2026-10-23_7d/README.md`.

2. Confirme quem é você. O período e o plano vêm da rodada, então a única pergunta é esta:

   ```
   Vou enviar como seu-login, contando só PRs de: seu-login, voce@empresa.com. Confirma? (s/n)
   ```

   Se a rodada não tiver plano padrão, o comando pergunta o seu plano.

3. Pronto. O seu `<login>.json` foi gravado no repositório central com um commit seu. Se você rodar de novo, o arquivo é substituído.

   Para ver o JSON antes de enviar, use `exportar --rodada <id>` no lugar de `enviar`.

### Testes

Os testes recriam repositórios git com PRs seus e de uma colega, além de logs JSONL com duplicatas. Para o modo equipe, um repositório git bare local faz o papel de central, e o ciclo completo é testado: abrir, enviar e fechar.

```bash
python3 tests/test_rot.py
python3 tests/test_rot.py --gerar-exemplo   # regrava examples/exemplo-relatorio.txt
```

## Metodologia e limitações

O texto completo está em `skills/retorno-sobre-tokens/references/metodologia.md`. Em resumo:

**Produção.** É o diff do que entrou no ramo de produção:
- merge: do primeiro pai até o commit do merge;
- squash: o próprio commit;
- rebase sem `(#N)`: só entra se o `gh` listar o PR.

**Autoria.** Vale o login do GitHub quando o `gh` informa o autor do PR. Sem isso, vale o e-mail do primeiro commit do PR, ou o do próprio commit, no caso do squash. O e-mail `noreply` do GitHub casa com o login.

**Linha efetiva.** `max(adições, remoções)` por arquivo, somado. Rename puro conta zero e binário fica de fora. Linha em branco e mudança só de formatação contam.

**Tokens.** Só os JSONL locais do Claude Code nesta máquina, sem duplicatas (`message.id` + `requestId`). Registro com data sem fuso é ignorado e vira aviso.

**Preço.** Dólares por milhão de tokens, preço de lista global da API, conferido em 2026-10-23 em [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) e [claude.com/pricing](https://claude.com/pricing). O preço exige o nome exato, um apelido exato ou o nome base sem sufixo de data. O resto fica sem preço, com aviso.

**Assinatura.** Os valores usados:

| Plano | Mensalidade |
| --- | --- |
| Pro mensal | US$ 20 |
| Pro anual | US$ 200 por ano, rateado como 200/12 |
| Max 5x | US$ 100 |
| Max 20x | US$ 200 |

O custo proporcional é um custo fixo rateado no período. Ele não é a causa das linhas: quanto mais código entra, menor fica o custo por linha.

### Limitações

- **Tokens de entrada e de cache dominam o volume, mas não dizem quanto código saiu.** Num uso típico do Claude Code, a leitura de cache costuma passar de 90% dos tokens, porque cada resposta relê o contexto inteiro. Por isso o ROT não usa mais "linhas por milhão de tokens" como manchete. Ele mostra cada tipo de token com a sua fatia do custo. A única razão de volume que sobrou é **linhas efetivas por milhão de tokens de SAÍDA**, que é volume e não qualidade.
- **Linha não é valor.** Uma linha de correção crítica e uma linha de boilerplate pesam o mesmo.
- **Token sem PR não some.** O custo do período usa todos os tokens, inclusive os de exploração, revisão e PRs que ainda não foram mesclados. A ligação de uma sessão a um PR é heurística.
- **Uma máquina só.** O ROT lê os logs da máquina onde roda. Conversa na web, outro computador e log apagado não aparecem. No modo equipe, cada dev mede a própria máquina.
- **Autoria por e-mail é frágil sem `gh`.** Se você commita com e-mails diferentes, liste todos em `autores.emails`.
- **Modelo novo fica sem preço** até alguém editar a tabela. O relatório avisa, mas o equivalente de API fica subestimado enquanto isso.
- **Não medimos** quem escreveu a linha (pessoa ou modelo), descontos, uso em lote, Bedrock, impostos, salário, hora economizada nem resultado de negócio.

## Exemplo de saída

Esta saída vem de uma execução de verdade sobre a fixture dos testes: o repositório `sample-app`, 7 dias terminando em 23/10/2026 15:00 UTC, Claude Max 5x, câmbio 5,0383. Nela:

- O PR #1 reescreve código e traz lockfile, vendor, gerado e snapshot, que ficam fora.
- O PR #2 é um squash de 5 linhas.
- O PR #3 é de uma colega e fica fora da conta.
- Um commit direto no `main` não entra.
- Os logs têm uma resposta gravada três vezes no streaming, uma sessão retomada e um arquivo de subagente copiado: cada resposta conta uma vez.
- Um modelo fora da tabela aparece como sem preço.

O custo usado é a assinatura proporcional: US$ 23,00. A mesma saída está em `skills/retorno-sobre-tokens/examples/exemplo-relatorio.txt`.

```
========================================================================
  ROT — Retorno sobre Tokens
  7 dias · 16/10/2026 15:00 UTC → 23/10/2026 15:00 UTC
  Plano: Claude Max 5x · US$ 100,00/mês
========================================================================

TOKENS
  Logs em ~/.claude/projects
  Tipo                              Tokens       Custo API  % do custo
  Entrada                        1.020.500        US$ 3,06       62,3%
  Saída                            103.000        US$ 1,54       31,4%
  Gravação de cache (5 min)          1.000      US$ 0,0037        0,1%
  Gravação de cache (1 h)            1.000      US$ 0,0060        0,1%
  Leitura de cache               1.000.000      US$ 0,3000        6,1%
  Total                          2.125.500        US$ 4,91
  Sem preço (fora do custo)            500
  Sessões no período                     4
  Duplicatas descartadas: 3 registros repetidos e 1 arquivo idêntico.

CÓDIGO EM PRODUÇÃO
  sample-app · ramo main · fonte: git
    PR #1        79d3ef9  23 linhas efetivas  (+19 −13, saldo +6)
      Merge pull request #1 from dev/feature
    PR #2        2eb6a16  5 linhas efetivas  (+5 −0, saldo +5)
      Adiciona healthcheck (#2)

  Linhas efetivas                             28
  Adições                                     24
  Remoções                                    13
  Saldo                                      +11
  Fora da conta (adições + remoções): 100 em lockfiles, 50 em código vendorizado, 62 em arquivos gerados, 20 em snapshots.
  Autor considerado: dev@example.com (fonte: --autor).
  PRs de outros autores fora da conta: 1 (6 linhas efetivas, 1 autor).

CUSTO
  Equivalente de API                        US$ 4,91
  Assinatura proporcional                  US$ 23,00
    US$ 100,00 × 7/30,4375 dias
  Custo usado nos indicadores              US$ 23,00
    Caixa da assinatura neste período, não o preço de tabela da API.
  Em reais                                 R$ 115,87
    US$ 1 = R$ 5,0383. Câmbio editável em rot_config.json.
    Equivalente de API em reais: R$ 24,76.

INDICADORES
  Custo por linha efetiva                             US$ 0,8214
  O mesmo em reais                                    R$ 4,14
  Equivalente de API por linha efetiva                US$ 0,1755
  Linhas efetivas por milhão de tokens de SAÍDA       271,84

POR REPOSITÓRIO
  sample-app: 28 linhas efetivas, 2.125.000 tokens na pasta, API US$ 4,91

AVISOS
  ! 1 evento com tokens sem data confiável (fuso ausente ou inválido) foi ignorado.
  !! ATENÇÃO: o modelo 'claude-inexistente' não tem preço em rot_config.json. 500 tokens SEM PREÇO ficaram fora do custo — o equivalente de API está subestimado. Acrescente o modelo à tabela, ou um apelido exato em model_aliases.

RESSALVAS
  - Linha efetiva é, por arquivo de texto, o maior valor entre adições e remoções. Uma refatoração que troca 100 linhas por 100 conta 100 — não 200 e não zero. Arquivos diferentes não se cancelam.
  - Entram mudanças que chegaram ao ramo de produção por commit de merge ou por assunto de pull request (Merge pull request #N ou sufixo (#N)). Commit direto, sem PR, fica de fora. Rebase sem número no assunto só entra se o GitHub CLI informar o PR.
  - Lockfile, código vendorizado, arquivo gerado e snapshot saem da conta pelo caminho. Um gerado com nome fora da lista entra. As listas estão em rot_config.json.
  - Os tokens vêm só dos JSONL locais do Claude Code nesta máquina. Conversa na web, outro aplicativo e log apagado não aparecem.
  - O custo da assinatura é a mensalidade proporcional ao período (mês de 30,4375 dias, que é 365,25/12). É um custo fixo rateado, não a causa das linhas: quanto mais código entra em produção, menor fica o custo por linha.
  - O equivalente de API usa a tabela publicada e editável, e só casa o nome exato do modelo (ou um apelido exato em model_aliases, ou o nome sem sufixo de data -AAAAMMDD quando a tabela lista o nome base). Modelo sem linha fica sem preço: os tokens aparecem à parte e não entram no dólar. Gravação de cache sem o detalhe de 5 minutos ou 1 hora é cobrada como 5 minutos.
  - O Claude Code grava a mesma resposta várias vezes (streaming, sessão retomada, sidechain). Cada resposta conta uma vez, pela dupla message.id + requestId, com o maior uso registrado.
  - Só entram PRs de sua autoria: login do GitHub quando o gh informa o autor, senão o e-mail do primeiro commit do PR. PRs de colegas mesclados no mesmo ramo ficam fora e aparecem só como contagem.
  - Linhas por milhão de tokens de saída é uma razão de volume, não de qualidade. Ela ignora entrada e cache, que dependem do tamanho do contexto e não do código produzido.
  - Atribuição de token a um PR é heurística (pasta da sessão, menção ao número, janela do PR). O total do período é a medida firme.
  - Isto não é ROI de negócio. Não estima salário, hora economizada, receita nem risco.
  - O real usa a taxa editável de 5,0383 reais por dólar (2026-10-22). Não é cotação ao vivo. O dólar continua sendo a moeda base.
========================================================================
```
