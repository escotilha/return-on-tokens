#!/usr/bin/env python3
"""Modo equipe do ROT: rodadas num repositório central.

Fluxo:
  1. O CTO abre a rodada (`abrir-rodada`). O período fica fixo em
     <rodada>/rodada.json e um <rodada>/README.md explica o que fazer.
  2. Cada dev roda `enviar --rodada <id>`. A conta é feita na máquina dele,
     só com os PRs de autoria dele, e vira <rodada>/<login>.json.
  3. O CTO fecha a rodada (`fechar-rodada`): vê quem enviou, quem falta, e
     recebe o total da equipe e uma linha por dev.

O repositório central pode ser uma URL git (GitHub ou outro) ou uma pasta
local. O envio usa as credenciais git de quem roda o comando. Nenhum
conteúdo de prompt e nenhum caminho local vai para o arquivo enviado.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import rotlib

SCHEMA_VERSION = 1
ROUND_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LOGIN_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
GITHUB_REMOTE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$"
)
GENERIC_REMOTE = re.compile(r"^(?:[a-z+]+://(?:[^@/]+@)?[^/]+/|[^@/]+@[^:]+:)(?P<slug>.+?)(?:\.git)?/?$")


class TeamError(rotlib.UsageError):
    """Erro do modo equipe. Sai com código 2."""


# ---------------------------------------------------------------------------
# Repositório central


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)


def looks_like_url(target: str) -> bool:
    return "://" in target or bool(re.match(r"^[^@/\s]+@[^:/\s]+:", target))


class Central:
    """Repositório central da equipe: clone git em cache, ou pasta simples."""

    def __init__(self, target: str, branch: str = "main", cache_dir: Path | None = None):
        if not target:
            raise TeamError(
                "Falta o repositório central. Passe --repo-central URL (ou uma pasta) "
                "ou preencha equipe.repositorio_central em rot_config.json."
            )
        self.target = target
        self.branch = branch or "main"
        path = Path(target).expanduser()
        self.is_git = looks_like_url(target) or (
            path.exists() and _run(["git", "-C", str(path), "rev-parse", "--git-dir"]).returncode == 0
        )
        if self.is_git:
            base = cache_dir or Path(os.environ.get("ROT_CACHE_DIR") or Path.home() / ".cache" / "rot-equipe")
            digest = hashlib.sha1(target.encode("utf-8")).hexdigest()[:12]
            self.root = Path(base).expanduser() / digest
        else:
            self.root = path

    # -- git -------------------------------------------------------------
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return _run(["git", "-C", str(self.root), *args])

    def _remote_has_branch(self) -> bool:
        result = self._git("ls-remote", "--heads", "origin", self.branch)
        if result.returncode != 0:
            raise TeamError(f"Não consegui falar com o repositório central: {result.stderr.strip()}")
        return bool(result.stdout.strip())

    def sync(self) -> None:
        if not self.is_git:
            self.root.mkdir(parents=True, exist_ok=True)
            return
        if not (self.root / ".git").exists():
            self.root.parent.mkdir(parents=True, exist_ok=True)
            cloned = _run(["git", "clone", "--quiet", self.target, str(self.root)])
            if cloned.returncode != 0:
                raise TeamError(
                    "Não consegui clonar o repositório central. Confira a URL e se você tem acesso "
                    f"(git clone {self.target}).\n{cloned.stderr.strip()}"
                )
        if self._remote_has_branch():
            fetched = self._git("fetch", "--quiet", "origin", self.branch)
            if fetched.returncode != 0:
                raise TeamError(f"git fetch falhou no repositório central: {fetched.stderr.strip()}")
            self._git("checkout", "--quiet", "-B", self.branch, f"origin/{self.branch}")
        else:
            # Repositório central recém-criado, sem nenhum commit.
            self._git("symbolic-ref", "HEAD", f"refs/heads/{self.branch}")

    def publish(self, files: dict[str, str], message: str) -> None:
        """Grava os arquivos (caminho relativo → texto) e, no modo git, faz commit e push."""
        self.sync()
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if not self.is_git:
            return
        self._git("add", "--", *files.keys())
        if not self._git("status", "--porcelain").stdout.strip():
            return
        committed = self._git("commit", "--quiet", "-m", message)
        if committed.returncode != 0:
            raise TeamError(
                "git commit falhou no repositório central. Configure user.name e user.email no git.\n"
                + committed.stderr.strip()
            )
        for attempt in range(2):
            pushed = self._git("push", "--quiet", "origin", f"HEAD:refs/heads/{self.branch}")
            if pushed.returncode == 0:
                return
            if attempt == 0 and self._remote_has_branch():
                self._git("pull", "--quiet", "--rebase", "origin", self.branch)
        raise TeamError(
            "git push falhou no repositório central. Confira se você tem permissão de escrita.\n"
            + pushed.stderr.strip()
        )

    def read_text(self, relative: str) -> str | None:
        path = self.root / relative
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def list_json(self, folder: str) -> list[Path]:
        base = self.root / folder
        if not base.is_dir():
            return []
        return sorted(path for path in base.glob("*.json") if path.name != "rodada.json")

    def link(self, relative: str) -> str:
        match = GITHUB_REMOTE.match(self.target)
        if match:
            return f"https://github.com/{match.group('slug')}/blob/{self.branch}/{relative}"
        if self.is_git:
            return f"{self.target} → {relative} (ramo {self.branch})"
        return str(self.root / relative)


GITHUB_LINK = re.compile(
    r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?:blob|tree)/(?P<branch>[\w./-]+?)/"
    r"(?P<round>[\w.-]+)(?:/README\.md)?/?$"
)


def central_from_link(link: str | None) -> tuple[str, str] | None:
    """Do link do README no GitHub, tira (URL do repositório central, ramo)."""
    match = GITHUB_LINK.match((link or "").strip())
    if not match:
        return None
    repo = match["repo"][:-4] if match["repo"].endswith(".git") else match["repo"]
    return f"https://github.com/{match['owner']}/{repo}.git", match["branch"]


def central_from(args, config: dict) -> Central:
    team = config.get("equipe") or {}
    derived = central_from_link(getattr(args, "rodada", None))
    target = (
        getattr(args, "repo_central", None)
        or (derived[0] if derived else None)
        or team.get("repositorio_central")
        or ""
    )
    branch = (
        getattr(args, "ramo", None)
        or (derived[1] if derived and target == derived[0] else None)
        or team.get("ramo")
        or "main"
    )
    cache = getattr(args, "cache_dir", None) or team.get("pasta_cache") or None
    return Central(str(target), branch, Path(cache).expanduser() if cache else None)


# ---------------------------------------------------------------------------
# Rodada


def check_round_id(value: str) -> str:
    if not value or not ROUND_ID.match(value):
        raise TeamError(
            f"Identificador de rodada inválido: {value!r}. Use letras, números, ponto, hífen ou "
            "sublinhado, por exemplo 2026-10-23_7d."
        )
    return value


def round_id_from_link(value: str) -> str:
    """Aceita o id puro ou o link do README da rodada."""
    value = value.strip().rstrip("/")
    if value.endswith("/README.md"):
        value = value[: -len("/README.md")]
    if "/" in value:
        value = value.rsplit("/", 1)[1]
    return check_round_id(value)


def default_round_id(period_id: str, end: dt.datetime) -> str:
    return f"{end.date().isoformat()}_{period_id}"


def roster_from(config: dict, explicit: list[str] | None) -> list[str]:
    if explicit:
        names: list[str] = []
        for item in explicit:
            names.extend(part.strip() for part in item.split(",") if part.strip())
        return sorted(dict.fromkeys(names))
    team = config.get("equipe") or {}
    return sorted(dict.fromkeys(str(item).strip() for item in team.get("devs") or [] if str(item).strip()))


def round_readme(meta: dict) -> str:
    period = meta["period"]
    start = rotlib.format_dt(rotlib.parse_ts(period["start"]))
    end = rotlib.format_dt(rotlib.parse_ts(period["end"]))
    command = (
        "python3 ~/.claude/skills/retorno-sobre-tokens/scripts/rot_report.py enviar "
        f"--rodada {shlex.quote(meta['rodada'])} "
        f"--repo-central {shlex.quote(meta['repositorio_central'])} "
        f"--ramo {shlex.quote(meta['ramo'])}"
    )
    roster = ", ".join(meta["roster"]) if meta["roster"] else "(sem lista; qualquer dev pode enviar)"
    plan = meta.get("plano_padrao") or "cada dev informa o seu"
    return f"""# Rodada de ROT {meta['rodada']}

Esta pasta junta os números de Retorno sobre Tokens (ROT) da equipe num período fixo.
Cada dev mede na própria máquina os tokens do Claude Code e as linhas que **ele** levou
para produção por PR, e envia um arquivo `<login>.json` para cá. Nenhum prompt e nenhum
caminho local sai da máquina.

- **Período:** {period['label']}, de {start} a {end}. É o mesmo para todos.
- **Quem deve enviar:** {roster}
- **Plano padrão:** {plan}

## O que fazer (dev)

Tenha a skill instalada em `~/.claude/skills/retorno-sobre-tokens` e acesso de escrita a este
repositório. Depois rode, uma vez:

```bash
{command}
```

Ou peça ao Claude Code: **"roda o ROT da rodada {meta['rodada']}"**.

O comando confirma quem é você (login do GitHub), faz a conta e grava `{meta['rodada']}/<seu-login>.json`
aqui com um commit seu. Se rodar de novo, o arquivo é substituído.

## O que acontece depois

Quem abriu a rodada roda `rot_report.py fechar-rodada --rodada {meta['rodada']}` e recebe o
total da equipe e uma linha por pessoa.
"""


def open_round(
    *,
    central: Central,
    config: dict,
    period_id: str,
    now: dt.datetime,
    round_id: str | None,
    roster: list[str],
    plan_default: str | None,
    opened_by: str | None,
    replace: bool = False,
) -> dict:
    start, end = rotlib.period_bounds(period_id, now)
    rodada = check_round_id(round_id or default_round_id(period_id, end))
    if plan_default:
        try:
            rotlib.plan_spec(config, plan_default, None, None)
        except ValueError as exc:
            raise TeamError(f"Plano padrão inválido: {plan_default}.") from exc
    central.sync()
    if central.read_text(f"{rodada}/rodada.json") is not None and not replace:
        raise TeamError(
            f"A rodada {rodada} já existe no repositório central. Use outro --rodada, ou --substituir."
        )
    meta = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": rotlib.TOOL_VERSION,
        "rodada": rodada,
        "period": {
            "id": period_id,
            "label": rotlib.PERIOD_LABELS[period_id],
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "roster": roster,
        "plano_padrao": plan_default or None,
        "repositorio_central": central.target,
        "ramo": central.branch,
        "aberta_em": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "aberta_por": opened_by,
    }
    central.publish(
        {
            f"{rodada}/rodada.json": json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            f"{rodada}/README.md": round_readme(meta),
        },
        f"ROT: abre a rodada {rodada}",
    )
    meta["link"] = central.link(f"{rodada}/README.md")
    return meta


def load_round(central: Central, rodada: str) -> dict | None:
    text = central.read_text(f"{rodada}/rodada.json")
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise TeamError(f"{rodada}/rodada.json está corrompido: {exc}") from exc


# ---------------------------------------------------------------------------
# Envio do dev


def remote_slug(repo_path: str) -> str:
    """owner/repo do remoto origin, sem credencial. Sem remoto, o nome da pasta."""
    result = _run(["git", "-C", repo_path, "remote", "get-url", "origin"])
    url = result.stdout.strip() if result.returncode == 0 else ""
    for pattern in (GITHUB_REMOTE, GENERIC_REMOTE):
        match = pattern.match(url)
        if match:
            return match.group("slug")
    return Path(repo_path).name


def pr_key(pr: dict, slug: str, github: bool) -> str:
    if pr.get("url"):
        return str(pr["url"])
    if pr.get("number") is not None:
        if github:
            return f"https://github.com/{slug}/pull/{pr['number']}"
        return f"{slug}#{pr['number']}"
    return f"{slug}@{pr['sha']}"


def build_submission(report: dict, rodada: str, login: str) -> dict:
    """Arquivo enviado ao repositório central. Sem prompt, sem caminho local."""
    slugs: dict[str, tuple[str, bool]] = {}
    prs = []
    for pr in report["pull_requests"]:
        path = pr["repo_path"]
        if path not in slugs:
            url = _run(["git", "-C", path, "remote", "get-url", "origin"]).stdout.strip()
            slugs[path] = (remote_slug(path), bool(GITHUB_REMOTE.match(url)))
        slug, github = slugs[path]
        prs.append({
            "key": pr_key(pr, slug, github),
            "repo": slug,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("url"),
            "merged_at": pr.get("committed_at"),
            "effective": pr["loc"]["effective"],
            "additions": pr["loc"]["additions"],
            "deletions": pr["loc"]["deletions"],
        })
    tokens = report["tokens"]
    cost = report["cost"]
    plan = report["plan"]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": rotlib.TOOL_VERSION,
        "rodada": rodada,
        "login": login,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "period": {
            "id": report["period"]["id"],
            "start": report["period"]["start"],
            "end": report["period"]["end"],
        },
        "plan": {
            "id": plan["id"],
            "label": plan["label"],
            "kind": plan["kind"],
            "monthly_usd": plan.get("monthly_usd"),
        },
        "tokens": {
            "input": tokens["input"],
            "output": tokens["output"],
            "cache_write_5m": tokens["cache_write_5m"],
            "cache_write_1h": tokens["cache_write_1h"],
            "cache_read": tokens["cache_read"],
            "total": tokens["total"],
            "cost_by_type_usd": tokens["cost_by_type_usd"],
            "unpriced_total": tokens["unpriced_total"],
            "unpriced_by_model": tokens["unpriced_tokens"],
            "by_model_tokens": tokens["by_model_tokens"],
        },
        "cost": {
            "api_equivalent_usd": cost["api_equivalent_usd"],
            "subscription_prorated_usd": cost["subscription_prorated_usd"],
            "primary_usd": cost["primary_usd"],
            "primary_basis": cost["primary_basis"],
        },
        "loc": {
            "effective": report["loc"]["effective"],
            "additions": report["loc"]["additions"],
            "deletions": report["loc"]["deletions"],
        },
        "pull_requests": prs,
        "other_authors_excluded": {
            "pull_requests": report["other_authors"]["pull_requests"],
            "effective": report["other_authors"]["effective"],
        },
        "sessions": report["sessions"],
        "dedup": report.get("dedup"),
    }


def submit(
    *,
    central: Central,
    config: dict,
    rodada: str,
    login: str,
    plan_id: str | None,
    monthly_usd: float | None,
    plan_label: str | None,
    stdin_is_tty: bool,
    analyze_kwargs: dict,
    input_fn=input,
    dry_run: bool = False,
) -> tuple[dict, dict, str | None]:
    """Faz a conta do dev no período da rodada e publica <rodada>/<login>.json."""
    if not LOGIN_SAFE.match(login or ""):
        raise TeamError(f"Login inválido para nome de arquivo: {login!r}. Use --login.")
    if login.casefold() == "rodada":
        raise TeamError("O login 'rodada' é reservado para os metadados da rodada. Use --login com seu login do GitHub.")
    central.sync()
    meta = load_round(central, rodada)
    if meta is None:
        raise TeamError(
            f"A rodada {rodada} não existe no repositório central ({central.target}). "
            "Peça o link da rodada a quem abriu."
        )
    period_id = meta["period"]["id"]
    end = rotlib.parse_ts(meta["period"]["end"])
    plan = rotlib.resolve_plan(
        config,
        plan_id or meta.get("plano_padrao"),
        monthly_usd,
        plan_label,
        stdin_is_tty,
        input_fn=input_fn,
    )
    report = rotlib.analyze(now=end, period_id=period_id, plan=plan, config=config, **analyze_kwargs)
    payload = build_submission(report, rodada, login)
    if dry_run:
        return payload, meta, None
    relative = f"{rodada}/{login}.json"
    central.publish(
        {relative: json.dumps(payload, indent=2, ensure_ascii=False) + "\n"},
        f"ROT: envio de {login} para a rodada {rodada}",
    )
    return payload, meta, central.link(relative)


# ---------------------------------------------------------------------------
# Consolidação do CTO


def load_submissions(central: Central, rodada: str) -> tuple[list[dict], list[str]]:
    found: list[dict] = []
    problems: list[str] = []
    for path in central.list_json(rodada):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name} não pôde ser lido: {exc}")
            continue
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            problems.append(f"{path.name} tem schema_version diferente de {SCHEMA_VERSION}; ficou de fora.")
            continue
        data.setdefault("login", path.stem)
        found.append(data)
    found.sort(key=lambda item: str(item["login"]).lower())
    return found, problems


def missing_from(roster: list[str], submissions: list[dict]) -> list[str]:
    sent = {str(item["login"]).lower() for item in submissions}
    return [name for name in roster if name.lower() not in sent]


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " e " + names[-1]


def ask_missing(missing: list[str], input_fn=input, output_fn=None) -> bool:
    write = output_fn or (lambda text: print(text, file=sys.stderr))
    question = f"Faltam {join_names(missing)}. Gerar o total assim mesmo (s) ou esperar (n)?"
    while True:
        answer = input_fn(question + " ").strip().lower()
        if answer in {"s", "sim", "y", "yes"}:
            return True
        if answer in {"n", "nao", "não", "no"}:
            return False
        write("Responda s ou n.")


def consolidate(meta: dict | None, roster: list[str], submissions: list[dict], rodada: str) -> dict:
    keys = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read", "total", "unpriced_total")
    total_tokens = {key: 0 for key in keys}
    cost_by_type = {key: 0.0 for key in rotlib.TOKEN_TYPES}
    api = primary = 0.0
    unique_prs: dict[str, dict] = {}
    shared: set[str] = set()
    rows = []
    expected = (meta or {}).get("period")
    if expected is None and submissions:
        periods = [(item["period"]["start"], item["period"]["end"]) for item in submissions]
        common = max(set(periods), key=periods.count)
        expected = {"start": common[0], "end": common[1], "id": None}
    mismatched = []
    for item in submissions:
        tokens = item["tokens"]
        for key in keys:
            total_tokens[key] += int(tokens.get(key) or 0)
        for key in rotlib.TOKEN_TYPES:
            cost_by_type[key] += float((tokens.get("cost_by_type_usd") or {}).get(key) or 0.0)
        api += float(item["cost"]["api_equivalent_usd"])
        primary += float(item["cost"]["primary_usd"])
        for pr in item.get("pull_requests") or []:
            key = pr["key"]
            if key in unique_prs:
                shared.add(key)
            else:
                unique_prs[key] = pr
        period_ok = bool(expected) and (
            item["period"]["start"] == expected["start"] and item["period"]["end"] == expected["end"]
        )
        if not period_ok:
            mismatched.append(item["login"])
        effective = int(item["loc"]["effective"])
        rows.append({
            "login": item["login"],
            "effective": effective,
            "pull_requests": len(item.get("pull_requests") or []),
            "tokens": {key: int(tokens.get(key) or 0) for key in keys},
            "primary_usd": float(item["cost"]["primary_usd"]),
            "api_equivalent_usd": float(item["cost"]["api_equivalent_usd"]),
            "usd_per_effective_loc": rotlib.ratio(float(item["cost"]["primary_usd"]), effective),
            "plan": item["plan"]["label"],
            "period_ok": period_ok,
            "period": item["period"],
            "generated_at": item.get("generated_at"),
        })
    effective_total = sum(int(pr["effective"]) for pr in unique_prs.values())
    sent = [row["login"] for row in rows]
    lowered_roster = {name.lower() for name in roster}
    return {
        "rodada": rodada,
        "period": expected,
        "roster": roster,
        "sent": sent,
        "missing": missing_from(roster, submissions),
        "extra": [name for name in sent if roster and name.lower() not in lowered_roster],
        "mismatched_period": mismatched,
        "total": {
            "effective": effective_total,
            "pull_requests": len(unique_prs),
            "shared_pull_requests": len(shared),
            "tokens": total_tokens,
            "cost_by_type_usd": cost_by_type,
            "api_equivalent_usd": api,
            "primary_usd": primary,
            "usd_per_effective_loc": rotlib.ratio(primary, effective_total),
            "effective_loc_per_million_output_tokens": (
                rotlib.ratio(effective_total, total_tokens["output"] / 1_000_000) if total_tokens["output"] else None
            ),
        },
        "developers": rows,
    }


def _compact(value: float) -> str:
    if value >= 1_000_000:
        return rotlib.format_number(value / 1_000_000, 2) + " M"
    if value >= 10_000:
        return rotlib.format_number(value / 1_000, 1) + " mil"
    return rotlib.format_int(value)


def render_team(summary: dict, usd_brl: float = 0.0) -> str:
    lines: list[str] = []
    total = summary["total"]
    period = summary.get("period") or {}
    lines.append("=" * 72)
    lines.append(f"  ROT da equipe — rodada {summary['rodada']}")
    if period.get("start"):
        label = rotlib.PERIOD_LABELS.get(period.get("id") or "", "período")
        lines.append(
            f"  {label} · {rotlib.format_dt(rotlib.parse_ts(period['start']))} → "
            f"{rotlib.format_dt(rotlib.parse_ts(period['end']))}"
        )
    roster_size = len(summary["roster"])
    sent = summary["sent"]
    if roster_size:
        lines.append(f"  Enviaram: {len(sent)} de {roster_size}. " + (
            f"Faltam: {join_names(summary['missing'])}." if summary["missing"] else "Ninguém falta."
        ))
    else:
        lines.append(f"  Enviaram: {len(sent)} (rodada sem lista de devs).")
    lines.append("=" * 72)
    lines.append("")
    lines.append("TOTAL DA EQUIPE")
    lines.append(f"  {'Linhas efetivas (PRs únicos)':<40}{rotlib.format_int(total['effective']):>16}")
    lines.append(f"  {'PRs únicos':<40}{rotlib.format_int(total['pull_requests']):>16}")
    if total["shared_pull_requests"]:
        lines.append(
            f"  {total['shared_pull_requests']} PR(s) apareceram em mais de um envio e contaram uma vez no total."
        )
    for key, label in rotlib.TOKEN_LABELS:
        lines.append(f"  {'Tokens — ' + label.lower():<40}{rotlib.format_int(total['tokens'][key]):>16}")
    lines.append(f"  {'Tokens — total':<40}{rotlib.format_int(total['tokens']['total']):>16}")
    if total["tokens"]["unpriced_total"]:
        lines.append(f"  {'!! Tokens sem preço (fora do custo)':<40}{rotlib.format_int(total['tokens']['unpriced_total']):>16}")
    lines.append(f"  {'Equivalente de API':<40}{rotlib.format_usd(total['api_equivalent_usd']):>16}")
    lines.append(f"  {'Custo (planos de cada dev)':<40}{rotlib.format_usd(total['primary_usd']):>16}")
    if usd_brl:
        lines.append(f"  {'Em reais':<40}{rotlib.format_brl(total['primary_usd'] * usd_brl):>16}")
    per_line = total["usd_per_effective_loc"]
    lines.append(f"  {'Custo por linha efetiva':<40}{(rotlib.format_usd(per_line) if per_line is not None else 'não se aplica'):>16}")
    per_output = total["effective_loc_per_million_output_tokens"]
    lines.append(
        f"  {'Linhas por milhão de tokens de SAÍDA':<40}"
        f"{(rotlib.format_number(per_output, 2) if per_output is not None else 'não se aplica'):>16}"
    )
    lines.append("")
    lines.append("POR DESENVOLVEDOR")
    header = (
        f"  {'dev':<14}{'linhas':>8}{'PRs':>5}{'entrada':>10}{'saída':>10}"
        f"{'grav.cache':>11}{'leit.cache':>11}{'custo':>13}{'US$/linha':>12}{'sem preço':>11}"
    )
    lines.append(header)
    for row in summary["developers"]:
        tokens = row["tokens"]
        per = row["usd_per_effective_loc"]
        flag = "" if row["period_ok"] else "  !! período diferente"
        lines.append(
            f"  {row['login'][:14]:<14}{rotlib.format_int(row['effective']):>8}{row['pull_requests']:>5}"
            f"{_compact(tokens['input']):>10}{_compact(tokens['output']):>10}"
            f"{_compact(tokens['cache_write_5m'] + tokens['cache_write_1h']):>11}"
            f"{_compact(tokens['cache_read']):>11}"
            f"{rotlib.format_usd(row['primary_usd']):>13}"
            f"{(rotlib.format_usd(per) if per is not None else '—'):>12}"
            f"{_compact(tokens['unpriced_total']):>11}{flag}"
        )
    for name in summary["missing"]:
        lines.append(f"  {name[:14]:<14}{'não enviou':>8}")
    notes = []
    if summary["mismatched_period"]:
        notes.append(
            f"!! Período diferente do da rodada: {join_names(summary['mismatched_period'])}. "
            "Peça para enviarem de novo com `enviar --rodada`."
        )
    if summary["extra"]:
        notes.append(f"Enviaram sem estar na lista da rodada: {join_names(summary['extra'])}.")
    if total["tokens"]["unpriced_total"]:
        notes.append("!! Há tokens sem preço: o custo de API da equipe está subestimado. Veja unpriced_by_model nos envios.")
    if summary.get("problems"):
        notes.extend(summary["problems"])
    if notes:
        lines.append("")
        lines.append("AVISOS")
        for note in notes:
            lines.append(f"  {note}" if note.startswith("!") else f"  ! {note}")
    lines.append("")
    lines.append("COMO LER")
    lines.append("  - Cada dev mediu só os PRs de autoria dele. Um PR enviado por duas pessoas conta uma vez no total.")
    lines.append("  - Custo é o plano de cada dev rateado no período (ou o preço de API, para quem paga por token).")
    lines.append("  - Tokens vêm dos logs locais do Claude Code de cada máquina, sem duplicatas.")
    lines.append("=" * 72)
    return "\n".join(lines)


def summary_markdown(text: str, rodada: str) -> str:
    return f"# Resumo da rodada {rodada}\n\nGerado por `rot_report.py fechar-rodada`.\n\n```\n{text}\n```\n"


def close_round(
    *,
    central: Central,
    config: dict,
    rodada: str,
    generate_anyway: bool,
    stdin_is_tty: bool,
    input_fn=input,
    output_fn=None,
) -> dict | None:
    """Devolve o resumo, ou None se o CTO preferir esperar quem falta."""
    write = output_fn or (lambda text: print(text, file=sys.stderr))
    central.sync()
    meta = load_round(central, rodada)
    if meta is None:
        write(f"Aviso: {rodada}/rodada.json não existe; a lista de devs vem de rot_config.json.")
    roster = list((meta or {}).get("roster") or roster_from(config, None))
    submissions, problems = load_submissions(central, rodada)
    missing = missing_from(roster, submissions)
    write(f"Enviaram ({len(submissions)}): {join_names([item['login'] for item in submissions]) or 'ninguém'}.")
    if missing:
        write(f"Faltam ({len(missing)}): {join_names(missing)}.")
        if not generate_anyway:
            if not stdin_is_tty:
                raise TeamError(
                    f"Faltam {join_names(missing)}. Gerar o total assim mesmo (s) ou esperar (n)?\n"
                    "Este terminal não é interativo. Rode de novo com --gerar-mesmo-assim, ou espere os envios."
                )
            if not ask_missing(missing, input_fn=input_fn, output_fn=write):
                return None
    if not submissions:
        raise TeamError(f"Nenhum envio na rodada {rodada} ainda.")
    summary = consolidate(meta, roster, submissions, rodada)
    summary["problems"] = problems
    return summary


def publish_summary(central: Central, rodada: str, text: str) -> str:
    relative = f"{rodada}/resumo.md"
    central.publish({relative: summary_markdown(text, rodada)}, f"ROT: resumo da rodada {rodada}")
    return central.link(relative)
