---
name: return-on-tokens
description: "Mede Return on Tokens (ROT): tokens consumidos, custo e linhas de código que chegaram à produção. Use quando pedirem ROT, custo por linha, custo dos tokens, linhas efetivas enviadas, ou se o uso do Claude valeu a pena no período. Pergunta o período (24 horas, 7 dias, 15 dias ou 30 dias) e o plano. Não estima salário, hora economizada nem ROI de negócio."
user-invocable: true
allowed-tools: Bash, Read
---

# ROT — Return on Tokens

Mede, no período pedido, quanto código chegou ao ramo de produção e quanto isso custou em tokens do Claude Code. O dólar é a moeda base. O real aparece por uma taxa editável.

Não calcule valor/hora, tempo economizado, receita, risco nem ROI de negócio. Isso está fora desta versão.

O método completo está em `references/metodologia.md`.

## Antes de rodar, pergunte

Não assuma o período nem o plano. Pergunte, com estas palavras:

1. Qual período? 24 horas, 7 dias, 15 dias ou 30 dias.
2. Qual plano ou licença? API sob demanda, Claude Pro (mensal ou anual), Claude Max 5x, Claude Max 20x, ou outro (peça a mensalidade em dólares).

Se a pessoa já tiver respondido na mesma conversa, use essa resposta.

## Como rodar

O script fica em `scripts/rot_report.py`, na mesma pasta desta skill. Descubra o diretório do `SKILL.md` e rode a partir dele. Não use caminho fixo de máquina.

```bash
python3 scripts/rot_report.py --period 7d --plan max-5x
```

Períodos: `24h`, `7d`, `15d`, `30d`.

Planos: `api`, `pro-monthly`, `pro-annual`, `max-5x`, `max-20x`. Para outro plano: `--plan custom --monthly-usd 20 --plan-label "Nome"`.

Repositórios: repita `--repo /caminho/do/repo` para cada um que a pessoa nomear. Sem `--repo`, o script usa o git do diretório atual e os repositórios que aparecerem nos logs do período.

Logs: por padrão `~/.claude/projects`. Outra pasta só se a pessoa pedir (`--projects-dir`).

Mostre o relatório de texto. Use `--json` só se pedirem JSON. As chaves do JSON ficam em inglês de propósito.

Preço e câmbio saem de `scripts/rot_config.json`. Se um modelo aparecer em AVISOS, diga para editar a tabela. Não invente preço.

## O que entregar

Tokens (entrada, saída, cache), custo em dólar (equivalente de API e, na assinatura, a mensalidade proporcional), linhas efetivas, adições, remoções, saldo, custo por linha efetiva e linhas efetivas por milhão de tokens. Inclua o real quando a taxa estiver ligada. Leia as ressalvas em voz alta o bastante para a pessoa não tratar o número como ROI de negócio.
