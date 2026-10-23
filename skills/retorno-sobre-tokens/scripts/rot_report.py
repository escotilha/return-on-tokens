#!/usr/bin/env python3
"""Relatório ROT — tokens, custo e linhas que chegaram à produção.

Sem subcomando, mede só você (modo solo) e pergunta o período e o plano
quando o terminal é interativo.

Modo equipe:
  rot_report.py abrir-rodada --periodo 7d      (CTO: abre a rodada e devolve o link)
  rot_report.py enviar --rodada <id>           (dev: envia os próprios números)
  rot_report.py fechar-rodada --rodada <id>    (CTO: total da equipe; apelido: equipe)
  rot_report.py exportar --rodada <id>         (dev: mostra o JSON sem enviar)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import rotlib
import rot_equipe

TEAM_COMMANDS = {"abrir-rodada", "enviar", "exportar", "fechar-rodada", "equipe"}


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rot_report.py",
        description=(
            "ROT — Retorno sobre Tokens. Mede linhas que chegaram à produção, "
            "tokens dos logs locais do Claude Code e o custo no período."
        ),
        epilog=(
            "Qual período? 24 horas, 7 dias, 15 dias ou 30 dias. "
            "Exemplo: rot_report.py --period 7d --plan max-5x"
        ),
    )
    parser.add_argument(
        "--period",
        help="Período: 24h (24 horas), 7d (7 dias), 15d (15 dias) ou 30d (30 dias).",
    )
    parser.add_argument(
        "--plan",
        help="Plano: api, pro-monthly, pro-annual, max-5x, max-20x ou custom.",
    )
    parser.add_argument(
        "--monthly-usd",
        type=float,
        default=None,
        help="Mensalidade em dólares quando --plan custom.",
    )
    parser.add_argument(
        "--plan-label",
        default=None,
        help="Nome do plano no relatório, útil com --plan custom.",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Repositório git a incluir. Pode repetir. Sem isto, usa os repos dos logs e o diretório atual.",
    )
    parser.add_argument(
        "--no-cwd",
        action="store_true",
        help="Não inclui o repositório git do diretório atual.",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Ramo de produção. Padrão: ramo padrão do remoto, ou main/master/trunk.",
    )
    parser.add_argument(
        "--projects-dir",
        default=None,
        help="Pasta dos logs do Claude Code. Padrão: ~/.claude/projects.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Caminho do rot_config.json. Padrão: o arquivo ao lado deste script.",
    )
    parser.add_argument(
        "--no-gh",
        action="store_true",
        help="Não consulta o GitHub CLI. Os PRs saem só do histórico git.",
    )
    parser.add_argument(
        "--exchange-rate",
        type=float,
        default=None,
        help="Reais por dólar nesta execução. 0 omite o real. Padrão: usd_brl do config.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Instante final do período, em ISO-8601 com fuso. Padrão: agora.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime JSON. As chaves ficam em inglês; o relatório de texto sai em português.",
    )
    add_author_args(parser)
    return parser


def add_author_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--autor",
        action="append",
        default=[],
        help=(
            "Seu login do GitHub ou e-mail de commit. Pode repetir. Só PRs desse autor contam. "
            "Padrão: `autores` do config, `gh api user` e `git config user.email`."
        ),
    )
    parser.add_argument(
        "--so-com-sessao",
        action="store_true",
        help="Conta só PRs com sessão do Claude Code no mesmo repositório durante a janela do PR (ou até 2 dias antes).",
    )


def add_central_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-central", default=None, help="URL git (ou pasta) do repositório central da equipe.")
    parser.add_argument("--ramo", default=None, help="Ramo do repositório central. Padrão: main.")
    parser.add_argument("--cache-dir", default=None, help="Onde guardar o clone do repositório central. Padrão: ~/.cache/rot-equipe.")
    parser.add_argument("--config", default=None, help="Caminho do rot_config.json.")


def build_team_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rot_report.py", description="ROT — modo equipe.")
    sub = parser.add_subparsers(dest="command", required=True)

    opener = sub.add_parser("abrir-rodada", help="CTO: abre uma rodada com período fixo e devolve o link para os devs.")
    opener.add_argument("--periodo", "--period", dest="period", default=None, help="24h, 7d, 15d ou 30d.")
    opener.add_argument("--rodada", default=None, help="Identificador da rodada. Padrão: <data final>_<período>.")
    opener.add_argument("--devs", action="append", default=[], help="Logins de quem deve enviar (vírgula ou repetido). Padrão: equipe.devs do config.")
    opener.add_argument("--plano-padrao", default=None, help="Plano sugerido aos devs (api, pro-monthly, max-5x...).")
    opener.add_argument("--now", default=None, help="Fim do período, ISO-8601 com fuso. Padrão: agora.")
    opener.add_argument("--substituir", action="store_true", help="Reescreve uma rodada que já existe.")
    add_central_args(opener)

    for name in ("enviar", "exportar"):
        sender = sub.add_parser(name, help="Dev: mede os seus números no período da rodada" + (" e envia." if name == "enviar" else " e imprime o JSON."))
        sender.add_argument("--rodada", required=True, help="Id da rodada ou o link do README dela.")
        sender.add_argument("--login", default=None, help="Seu login (nome do arquivo). Padrão: equipe.login do config ou `gh api user`.")
        sender.add_argument("--plan", default=None, help="Seu plano. Padrão: o plano padrão da rodada.")
        sender.add_argument("--monthly-usd", type=float, default=None)
        sender.add_argument("--plan-label", default=None)
        sender.add_argument("--repo", action="append", default=[])
        sender.add_argument("--no-cwd", action="store_true")
        sender.add_argument("--branch", default=None)
        sender.add_argument("--projects-dir", default=None)
        sender.add_argument("--no-gh", action="store_true")
        sender.add_argument("--sim", action="store_true", help="Não pede confirmação de identidade.")
        if name == "exportar":
            sender.add_argument("--enviar", action="store_true", help="Além de imprimir, envia (igual a `enviar`).")
        add_author_args(sender)
        add_central_args(sender)

    for name in ("fechar-rodada", "equipe"):
        closer = sub.add_parser(name, help="CTO: junta os envios e mostra o total da equipe.")
        closer.add_argument("--rodada", required=True, help="Id da rodada ou o link do README dela.")
        closer.add_argument("--gerar-mesmo-assim", action="store_true", help="Gera o total mesmo faltando envios.")
        closer.add_argument("--gravar-resumo", action="store_true", help="Grava <rodada>/resumo.md no repositório central.")
        closer.add_argument("--exchange-rate", type=float, default=None)
        closer.add_argument("--json", action="store_true")
        add_central_args(closer)
    return parser


def resolve_login(args, config: dict) -> str:
    team = config.get("equipe") or {}
    login = args.login or team.get("login") or None
    if not login and not args.no_gh:
        login = rotlib.gh_user_login()
    if not login:
        raise rotlib.UsageError(
            "Não sei o seu login. Rode `gh auth login`, ou passe --login SEU_LOGIN_DO_GITHUB."
        )
    return login


def confirm(question: str) -> bool:
    answer = input(question + " ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


def team_main(argv: list[str]) -> int:
    args = build_team_parser().parse_args(argv)
    config = rotlib.load_config(Path(args.config) if args.config else None)
    central = rot_equipe.central_from(args, config)
    tty = sys.stdin.isatty()
    if args.command == "abrir-rodada":
        period_id = rotlib.resolve_period(args.period, tty)
        now = parse_now(args.now)
        opened_by = rotlib.gh_user_login() if not args.now else None
        meta = rot_equipe.open_round(
            central=central,
            config=config,
            period_id=period_id,
            now=now,
            round_id=args.rodada,
            roster=rot_equipe.roster_from(config, args.devs),
            plan_default=args.plano_padrao,
            opened_by=opened_by,
            replace=args.substituir,
        )
        print(f"Rodada {meta['rodada']} aberta: {meta['period']['label']}, "
              f"{rotlib.format_dt(rotlib.parse_ts(meta['period']['start']))} → "
              f"{rotlib.format_dt(rotlib.parse_ts(meta['period']['end']))}.")
        if meta["roster"]:
            print(f"Quem deve enviar: {rot_equipe.join_names(meta['roster'])}.")
        print("Mande este link para os devs:")
        print(meta["link"])
        return 0

    rodada = rot_equipe.round_id_from_link(args.rodada)
    if args.command in {"enviar", "exportar"}:
        login = resolve_login(args, config)
        use_gh = not args.no_gh
        repos = [Path(item).expanduser() for item in args.repo]
        identity = rotlib.resolve_identity(config, args.autor, True, repos, login_fetcher=lambda: login)
        who = ", ".join(identity["logins"] + identity["emails"])
        dry = args.command == "exportar" and not args.enviar
        if dry:
            print(f"Medindo como {login}, contando só PRs de: {who}. Nada será enviado.", file=sys.stderr)
        elif args.sim:
            print(f"Enviando como {login}; PRs de: {who}.", file=sys.stderr)
        elif tty:
            if not confirm(f"Vou enviar como {login}, contando só PRs de: {who}. Confirma? (s/n)"):
                print("Envio cancelado.", file=sys.stderr)
                return 1
        else:
            raise rotlib.UsageError(
                f"Vou enviar como {login}, contando só PRs de: {who}. Confirma? (s/n)\n"
                "Este terminal não é interativo. Se estiver certo, rode de novo com --sim; "
                "se não, use --login e --autor."
            )
        projects = Path(args.projects_dir).expanduser() if args.projects_dir else Path.home() / ".claude" / "projects"
        payload, meta, link = rot_equipe.submit(
            central=central,
            config=config,
            rodada=rodada,
            login=login,
            plan_id=args.plan,
            monthly_usd=args.monthly_usd,
            plan_label=args.plan_label,
            stdin_is_tty=tty,
            dry_run=dry,
            analyze_kwargs={
                "repos": repos,
                "projects_dir": projects,
                "use_gh": use_gh,
                "branch": args.branch,
                "include_cwd": not args.no_cwd,
                "identity": identity,
                "require_session": args.so_com_sessao,
            },
        )
        if dry:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        print(
            f"Enviado: {payload['loc']['effective']} linhas efetivas em {len(payload['pull_requests'])} PRs, "
            f"{rotlib.format_int(payload['tokens']['total'])} tokens, custo {rotlib.format_usd(payload['cost']['primary_usd'])}."
        )
        if payload["tokens"]["unpriced_total"]:
            print(f"!! {rotlib.format_int(payload['tokens']['unpriced_total'])} tokens sem preço (modelo fora da tabela).")
        print(f"Arquivo: {link}")
        return 0

    summary = rot_equipe.close_round(
        central=central,
        config=config,
        rodada=rodada,
        generate_anyway=args.gerar_mesmo_assim,
        stdin_is_tty=tty,
    )
    if summary is None:
        print("Tudo bem. Rode de novo quando os envios chegarem.")
        return 0
    rate = args.exchange_rate if args.exchange_rate is not None else float(config.get("usd_brl") or 0.0)
    text = rot_equipe.render_team(summary, max(rate, 0.0))
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(text)
    if args.gravar_resumo:
        print(f"Resumo gravado: {rot_equipe.publish_summary(central, rodada, text)}", file=sys.stderr)
    return 0


def parse_now(raw: str | None) -> dt.datetime:
    if not raw:
        return dt.datetime.now(dt.timezone.utc)
    now = rotlib.parse_ts(raw)
    if now is None:
        raise rotlib.UsageError(
            "Data inválida em --now. Use ISO-8601 com fuso, por exemplo 2026-10-23T15:00:00+00:00."
        )
    return now


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in TEAM_COMMANDS:
        try:
            return team_main(argv)
        except rotlib.UsageError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = rotlib.load_config(Path(args.config) if args.config else None)
        period_id = rotlib.resolve_period(args.period, sys.stdin.isatty())
        plan = rotlib.resolve_plan(
            config,
            args.plan,
            args.monthly_usd,
            args.plan_label,
            sys.stdin.isatty(),
        )
        now = parse_now(args.now)
        projects = Path(args.projects_dir).expanduser() if args.projects_dir else Path.home() / ".claude" / "projects"
        report = rotlib.analyze(
            now=now,
            period_id=period_id,
            plan=plan,
            repos=[Path(item).expanduser() for item in args.repo],
            projects_dir=projects,
            config=config,
            use_gh=not args.no_gh,
            branch=args.branch,
            exchange_rate=args.exchange_rate,
            include_cwd=not args.no_cwd,
            authors=args.autor,
            require_session=args.so_com_sessao,
        )
    except rotlib.UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(rotlib.render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
