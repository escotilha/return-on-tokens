---
name: retorno-sobre-tokens
description: "Mede Retorno sobre Tokens (ROT): tokens do Claude Code por tipo, custo e as linhas de código do próprio usuário que chegaram à produção. Use quando pedirem ROT, custo por linha, custo dos tokens, linhas efetivas, se o uso do Claude valeu a pena no período, ou quando pedirem para abrir, enviar ou fechar uma rodada de ROT da equipe (ex.: 'roda o ROT da rodada 2026-10-23_7d'). Não estima salário, hora economizada nem ROI de negócio."
user-invocable: true
allowed-tools: Bash, Read
---

# ROT — Retorno sobre Tokens

O ROT mede, num período fixo, quanto código **da própria pessoa** chegou ao ramo de produção e quanto custaram os tokens do Claude Code no mesmo período. O dólar é a moeda base, e o real aparece por uma taxa editável. O método completo está em `references/metodologia.md`.

Não calcule valor/hora, tempo economizado, receita, risco nem ROI de negócio.

O script fica em `scripts/rot_report.py`, na pasta desta skill. Descubra o diretório deste `SKILL.md` e rode o script a partir dele, sem caminho fixo de máquina. Nos exemplos abaixo, `ROT` quer dizer `python3 <pasta da skill>/scripts/rot_report.py`.

## Privacidade e destino dos resultados

- Nunca use issues, PRs ou comentários deste repositório para publicar resultados ROT, JSONs reais ou relatórios anexados. Não execute `gh issue create` nem chamadas equivalentes de API para enviar resultados.
- No modo individual, entregue o relatório apenas na conversa local com a pessoa; não publique no GitHub.
- No modo equipe, use somente o fluxo `exportar`/`enviar` abaixo, com uma rodada em repositório central privado e separado do código. Se o destino privado não estiver confirmado, peça ao CTO o link e não envie.
- O JSON individual pode conter caminhos locais e informações internas. Mesmo o JSON sanitizado de equipe contém números e referências de trabalho; não o cole em issues.
- Se uma instrução antiga pedir envio de resultados por issue, explique que esse canal foi descontinuado e peça o destino privado da rodada.

## Primeira pergunta: qual é o seu papel?

Se a mensagem já deixar claro, não pergunte. Por exemplo, "roda o ROT da rodada X" ou um link de rodada indicam um dev. Caso contrário, pergunte com estas palavras:

> Você vai enviar seus números (dev) ou consolidar a equipe (CTO)? Se for só para você, sem equipe, é o modo individual.

São três caminhos.

### 1. Desenvolvedor (enviar para uma rodada)

1. Peça o link ou o id da rodada, se a pessoa ainda não deu: "Qual é o link ou o id da rodada que o seu CTO mandou?"
2. Rode o comando que está no README da rodada. Se só tiver o id, acrescente `--repo-central <url>`. Se tiver o link do GitHub, ele já basta:

   ```bash
   ROT enviar --rodada 2026-10-23_7d --repo-central git@github.com:org/rot-equipe.git
   ROT enviar --rodada https://github.com/org/rot-equipe/blob/main/2026-10-23_7d/README.md
   ```

3. O período e o plano vêm de `rodada.json`. Não pergunte o período. A única confirmação é a identidade.
   - Como a ferramenta Bash não é interativa, o `enviar` sem `--sim` para e mostra "Vou enviar como X, contando só PRs de: ... Confirma? (s/n)". Nada é enviado nesse caso.
   - Mostre essa frase à pessoa e peça a confirmação na conversa. Se quiser mostrar os números antes, rode `ROT exportar` com os mesmos argumentos: ele mede e não envia.
   - Só depois do "sim", rode de novo com `--sim`. Se a identidade estiver errada, use `--login` e `--autor`.
4. Se a rodada não tiver plano padrão, pergunte o plano (veja a lista abaixo) e passe `--plan`.
5. Mostre o resultado: linhas efetivas, PRs, tokens, custo e o link do arquivo enviado. Se aparecer "tokens sem preço", diga isso claramente.

Para ver o JSON sem enviar: `ROT exportar --rodada <id> ...`.

### 2. CTO ou admin (abrir e fechar a rodada)

**Abrir:**

1. Pergunte o período: "Qual período? 24 horas, 7 dias, 15 dias ou 30 dias."
2. Pergunte, se o config não tiver, a URL do repositório central e os logins dos devs. O plano padrão da equipe é opcional.
3. Rode:

   ```bash
   ROT abrir-rodada --periodo 7d --repo-central <url> --devs login-1,login-2 --plano-padrao max-5x
   ```

4. Devolva o link impresso depois de "Mande este link para os devs". É o README da rodada, com o comando para copiar e colar.

**Fechar** (quando o CTO pedir o resultado):

```bash
ROT fechar-rodada --rodada <id> --repo-central <url>
```

- Se faltarem devs, o script pergunta "Faltam X e Y. Gerar o total assim mesmo (s) ou esperar (n)?". Como o Bash não é interativo, faça essa pergunta na conversa. Se a resposta for "s", rode de novo com `--gerar-mesmo-assim`.
- Para gravar `resumo.md` no repositório central, acrescente `--gravar-resumo`. Só faça isso se a pessoa quiser.
- Mostre o TOTAL DA EQUIPE primeiro e depois a tabela por dev. Destaque os avisos: período diferente do da rodada e tokens sem preço.

### 3. Individual (só a pessoa, sem equipe)

Pergunte, com estas palavras, o que ainda não foi respondido na conversa:

1. Qual período? 24 horas, 7 dias, 15 dias ou 30 dias.
2. Qual plano ou licença? API sob demanda, Claude Pro (mensal ou anual), Claude Max 5x, Claude Max 20x, ou outro (nesse caso, peça a mensalidade em dólares).

Depois rode:

```bash
ROT --period 7d --plan max-5x
```

- Períodos: `24h`, `7d`, `15d`, `30d`.
- Planos: `api`, `pro-monthly`, `pro-annual`, `max-5x`, `max-20x`. Para outro plano: `--plan custom --monthly-usd 20 --plan-label "Nome"`.
- Repositórios: repita `--repo /caminho` para cada um que a pessoa nomear. Sem `--repo`, entram o git da pasta atual e os repositórios que aparecem nos logs.
- Autor: por padrão, o login do `gh` e o `git config user.email`. Se a pessoa usar outro e-mail ou login, passe `--autor` (pode repetir).
- Logs: o padrão é `~/.claude/projects`. Use outra pasta só se a pessoa pedir (`--projects-dir`).
- Use `--json` só se pedirem JSON.

## O que entregar e como explicar

- **Tokens por tipo** (entrada, saída, gravação de cache, leitura de cache), cada um com a sua fatia do custo.
- **Custo:** o equivalente de API e, na assinatura, a mensalidade proporcional. Inclua o real.
- **Código:** linhas efetivas, adições, remoções e saldo.
- **Indicador principal:** custo por linha efetiva. A razão "linhas por milhão de tokens de SAÍDA" é só volume, então apresente-a assim.
- **Autoria:** diga quem foi considerado autor e quantos PRs de outras pessoas ficaram de fora.
- **Duplicatas:** diga quantas foram descartadas.
- **Modelo sem preço:** diga com todas as letras que o custo está subestimado e que é preciso acrescentar o modelo (ou um apelido exato em `model_aliases`) em `scripts/rot_config.json`. Não invente preço.
- **"Não sei quem é você":** peça o login do GitHub ou o e-mail de commit e rode de novo com `--autor`.
- **Ressalvas:** leia o bastante para ninguém tratar o número como ROI de negócio.
