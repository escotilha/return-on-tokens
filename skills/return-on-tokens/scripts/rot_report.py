#!/usr/bin/env python3
"""Relatório ROT — tokens, custo e linhas que chegaram à produção.

Pergunta o período e o plano quando o terminal é interativo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import rotlib


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
            "ROT — Return on Tokens. Mede linhas que chegaram à produção, "
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
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8()
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
        if args.now:
            now = rotlib.parse_ts(args.now)
            if now is None:
                raise rotlib.UsageError(
                    "Data inválida em --now. Use ISO-8601 com fuso, por exemplo 2026-10-23T15:00:00+00:00."
                )
        else:
            now = dt.datetime.now(dt.timezone.utc)
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
