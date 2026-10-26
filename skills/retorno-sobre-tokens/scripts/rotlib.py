#!/usr/bin/env python3
"""Núcleo do ROT — Retorno sobre Tokens.

Mede, num período, as linhas que chegaram ao ramo de produção e os tokens
dos logs locais do Claude Code. O dólar é a moeda base; o real é conversão
opcional por uma taxa editável.

Não estima salário, hora economizada nem ROI de negócio.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

TOOL_VERSION = "1.1.0"
MONTH_DAYS_DEFAULT = 365.25 / 12.0
PERIODS = {
    "24h": dt.timedelta(hours=24),
    "7d": dt.timedelta(days=7),
    "15d": dt.timedelta(days=15),
    "30d": dt.timedelta(days=30),
}
PERIOD_LABELS = {
    "24h": "24 horas",
    "7d": "7 dias",
    "15d": "15 dias",
    "30d": "30 dias",
}
PERIOD_ALIASES = {
    "1": "24h",
    "24": "24h",
    "24h": "24h",
    "24 horas": "24h",
    "24 horas.": "24h",
    "2": "7d",
    "7": "7d",
    "7d": "7d",
    "7 dias": "7d",
    "3": "15d",
    "15": "15d",
    "15d": "15d",
    "15 dias": "15d",
    "4": "30d",
    "30": "30d",
    "30d": "30d",
    "30 dias": "30d",
}
PLAN_ORDER = ("api", "pro-monthly", "pro-annual", "max-5x", "max-20x", "custom")
HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "rot_config.json"

PR_MERGE = re.compile(r"Merge pull request #(\d+)\b", re.IGNORECASE)
PR_SQUASH = re.compile(r"\(#(\d+)\)\s*$")
PR_MENTION = re.compile(r"(?:#|pull/)(\d+)\b")


class UsageError(Exception):
    """Argumento ausente ou inválido. O comando sai com código 2."""


def load_config(path: Path | None = None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with cfg_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data["_path"] = str(cfg_path)
    return data


def parse_ts(value: str | None) -> dt.datetime | None:
    """Aceita ISO-8601 com fuso. Data ingênua (sem fuso) é descartada."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def period_bounds(period_id: str, now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    if period_id not in PERIODS:
        raise ValueError(period_id)
    end = now.astimezone(dt.timezone.utc)
    return end - PERIODS[period_id], end


def normalize_period(answer: str) -> str | None:
    return PERIOD_ALIASES.get(answer.strip().lower())


def public_dict(table: dict) -> dict:
    return {
        key: value
        for key, value in table.items()
        if not str(key).startswith("_") and isinstance(value, dict)
    }


def format_number(value: float, decimals: int) -> str:
    """Milhar com ponto e decimal com vírgula."""
    sign = "-" if value < 0 else ""
    raw = f"{abs(value):.{decimals}f}"
    if decimals:
        whole, frac = raw.split(".")
    else:
        whole, frac = raw, None
    groups: list[str] = []
    while whole:
        groups.append(whole[-3:])
        whole = whole[:-3]
    whole_fmt = ".".join(reversed(groups)) or "0"
    if frac is None:
        return sign + whole_fmt
    return sign + whole_fmt + "," + frac


def format_int(value: int | float) -> str:
    return format_number(float(value), 0)


def format_signed_int(value: int) -> str:
    if value > 0:
        return "+" + format_int(value)
    return format_int(value)


def format_usd(value: float, decimals: int | None = None) -> str:
    if decimals is None:
        decimals = 2 if abs(value) >= 1 else 4
    return "US$ " + format_number(value, decimals)


def format_brl(value: float, decimals: int | None = None) -> str:
    if decimals is None:
        decimals = 2 if abs(value) >= 1 else 4
    return "R$ " + format_number(value, decimals)


def format_dt(moment: dt.datetime) -> str:
    moment = moment.astimezone(dt.timezone.utc)
    return moment.strftime("%d/%m/%Y %H:%M UTC")


def _git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=text,
        check=False,
    )


_MAIN_WORKTREE: dict[str, Path] = {}


def main_worktree(root: Path) -> Path:
    """Uma worktree ligada devolve o checkout principal.

    Várias pastas do mesmo repositório (worktrees de PR, por exemplo) compartilham
    o ramo de produção. Sem isto, o mesmo PR entraria uma vez por pasta.
    """
    resolved = root.resolve()
    cached = _MAIN_WORKTREE.get(str(resolved))
    if cached is not None:
        return cached
    listed = _git(resolved, "worktree", "list", "--porcelain")
    chosen = resolved
    if listed.returncode == 0:
        for line in listed.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            candidate = Path(line[len("worktree "):])
            if candidate.exists():
                chosen = candidate.resolve()
            break
    _MAIN_WORKTREE[str(resolved)] = chosen
    _MAIN_WORKTREE[str(chosen)] = chosen
    return chosen


def find_git_root(cwd: str | None, cache: dict[str, Path | None]) -> Path | None:
    if not cwd:
        return None
    if cwd in cache:
        return cache[cwd]
    path = Path(cwd)
    if not path.exists():
        cache[cwd] = None
        return None
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        cache[cwd] = None
        return None
    root = main_worktree(Path(result.stdout.strip()))
    cache[cwd] = root
    return root


def detect_default_branch(repo: Path, configured: str | None = None) -> str:
    if configured:
        return configured
    origin = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if origin.returncode == 0 and origin.stdout.strip():
        return origin.stdout.strip().split("/", 1)[-1]
    for candidate in ("main", "master", "trunk"):
        if _git(repo, "rev-parse", "--verify", "--quiet", candidate).returncode == 0:
            return candidate
    current = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    name = current.stdout.strip()
    return name or "HEAD"


def commit_exists(repo: Path, sha: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def commit_parents(repo: Path, sha: str) -> list[str]:
    result = _git(repo, "rev-parse", f"{sha}^@")
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.split() if line]


def parent_of(repo: Path, sha: str) -> str | None:
    result = _git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def commit_meta(repo: Path, sha: str) -> tuple[dt.datetime | None, list[str], str]:
    result = _git(repo, "log", "-1", "--format=%cI%x1f%P%x1f%s", sha)
    if result.returncode != 0:
        return None, [], ""
    parts = result.stdout.strip("\n").split("\x1f", 2)
    if len(parts) != 3:
        return None, [], ""
    when = parse_ts(parts[0])
    parents = parts[1].split() if parts[1] else []
    return when, parents, parts[2]


def pr_number_from_subject(subject: str) -> int | None:
    match = PR_MERGE.search(subject) or PR_SQUASH.search(subject)
    if not match:
        return None
    return int(match.group(1))


def is_shipped_commit(subject: str, parents: list[str]) -> bool:
    # Merge de dois pais chegou ao ramo. Squash do GitHub termina com (#N).
    if len(parents) >= 2:
        return True
    return pr_number_from_subject(subject) is not None


def parse_numstat_z(data: bytes) -> list[dict]:
    """Lê `git diff -M -z --numstat`.

    Arquivo comum: adições \\t remoções \\t caminho \\0
    Rename: adições \\t remoções \\t \\0 antigo \\0 novo \\0
    Binário: o campo numérico vem como '-'.
    """
    entries: list[dict] = []
    index = 0
    length = len(data)
    while index < length:
        try:
            tab1 = data.index(b"\t", index)
            tab2 = data.index(b"\t", tab1 + 1)
        except ValueError:
            break
        added_raw = data[index:tab1]
        deleted_raw = data[tab1 + 1:tab2]
        index = tab2 + 1
        if index >= length:
            break
        old_path = None
        if data[index:index + 1] == b"\0":
            index += 1
            old_end = data.index(b"\0", index)
            new_end = data.index(b"\0", old_end + 1)
            old_path = data[index:old_end].decode("utf-8", "replace")
            path = data[old_end + 1:new_end].decode("utf-8", "replace")
            index = new_end + 1
        else:
            end = data.index(b"\0", index)
            path = data[index:end].decode("utf-8", "replace")
            index = end + 1
        added = None if added_raw == b"-" else int(added_raw)
        deleted = None if deleted_raw == b"-" else int(deleted_raw)
        entries.append({
            "added": added,
            "deleted": deleted,
            "path": path,
            "old_path": old_path,
            "binary": added is None or deleted is None,
        })
    return entries


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in patterns]


def exclusion_reason(path: str, cfg: dict) -> str | None:
    rules = cfg.get("exclude", {})
    name = Path(path).name
    if name in set(rules.get("lockfile_basenames", [])):
        return "lockfile"
    for label, key in (
        ("vendored", "vendored_path_regex"),
        ("generated", "generated_path_regex"),
        ("snapshot", "snapshot_path_regex"),
    ):
        for pattern in _compile_patterns(rules.get(key, [])):
            if pattern.search(path):
                return label
    return None


def empty_loc() -> dict:
    return {
        "additions": 0,
        "deletions": 0,
        "effective": 0,
        "binary_files": 0,
        "excluded": {
            "lockfile": {"files": 0, "lines": 0},
            "vendored": {"files": 0, "lines": 0},
            "generated": {"files": 0, "lines": 0},
            "snapshot": {"files": 0, "lines": 0},
        },
    }


def add_loc(total: dict, part: dict) -> None:
    total["additions"] += part["additions"]
    total["deletions"] += part["deletions"]
    total["effective"] += part["effective"]
    total["binary_files"] += part["binary_files"]
    for key, bucket in part["excluded"].items():
        dest = total["excluded"][key]
        dest["files"] += bucket["files"]
        dest["lines"] += bucket["lines"]


def loc_from_numstat(entries: list[dict], cfg: dict) -> dict:
    """Linha efetiva por arquivo = max(adições, remoções).

    Uma reescrita de 8 por 8 conta 8, não 16 e não 0. A soma é por arquivo,
    então um arquivo novo e outro apagado não se anulam.
    """
    stats = empty_loc()
    for entry in entries:
        if entry["binary"]:
            stats["binary_files"] += 1
            continue
        reason = exclusion_reason(entry["path"], cfg)
        added = int(entry["added"])
        deleted = int(entry["deleted"])
        if reason:
            bucket = stats["excluded"][reason]
            bucket["files"] += 1
            bucket["lines"] += added + deleted
            continue
        stats["additions"] += added
        stats["deletions"] += deleted
        stats["effective"] += max(added, deleted)
    return stats


def diff_loc(repo: Path, parent: str, commit: str, cfg: dict) -> dict:
    result = _git(repo, "diff", "-M", "-z", "--numstat", parent, commit, text=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return loc_from_numstat(parse_numstat_z(result.stdout), cfg)


def landed_range(repo: Path, sha: str, oids: list[str] | None) -> tuple[str, str] | None:
    """Intervalo cujo diff é o que de fato entrou no ramo.

    Merge com dois pais: primeiro pai → commit do merge.
    Rebase: do pai do primeiro commit que está no ramo até o último.
    Squash: os commits originais não são ancestrais do squash; o diff é o
    próprio commit espremido.
    """
    parents = commit_parents(repo, sha)
    if len(parents) >= 2:
        return parents[0], sha
    if oids:
        landed = [
            oid for oid in oids
            if commit_exists(repo, oid) and is_ancestor(repo, oid, sha)
        ]
        if landed:
            first_parent = parent_of(repo, landed[0])
            if first_parent:
                return first_parent, landed[-1]
    first_parent = parent_of(repo, sha)
    if not first_parent:
        return None
    return first_parent, sha


def work_window(repo: Path, sha: str, parents: list[str], merged_at: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    if len(parents) >= 2:
        listed = _git(repo, "log", "--format=%cI", f"{parents[0]}..{parents[1]}")
        moments = [parse_ts(line) for line in listed.stdout.splitlines()]
        moments = [item for item in moments if item is not None]
        if moments:
            return min(moments), merged_at
    return merged_at, merged_at


def iter_first_parent(repo: Path, branch: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    # Folga de um dia no pré-filtro do git; o corte exato é feito em Python.
    since = (start - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    until = end.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    result = _git(
        repo,
        "log",
        branch,
        "--first-parent",
        f"--since={since}",
        f"--until={until}",
        "--format=%H%x1f%cI%x1f%P%x1f%s",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git log falhou em {repo}")
    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        when = parse_ts(parts[1])
        if when is None or when < start or when >= end:
            continue
        parents = parts[2].split() if parts[2] else []
        commits.append({
            "sha": parts[0],
            "when": when,
            "parents": parents,
            "subject": parts[3],
        })
    return commits


def pr_record(
    repo: Path,
    sha: str,
    when: dt.datetime,
    parents: list[str],
    title: str,
    cfg: dict,
    number: int | None = None,
    url: str | None = None,
    oids: list[str] | None = None,
    kind: str | None = None,
) -> dict | None:
    bounds = landed_range(repo, sha, oids)
    if bounds is None:
        return None
    parent, tip = bounds
    loc = diff_loc(repo, parent, tip, cfg)
    author_email = first_author_email(repo, parent, tip, sha)
    if kind is None:
        kind = "merge" if len(parents) >= 2 else "squash"
    window_start, window_end = work_window(repo, sha, parents, when)
    return {
        "repo_path": str(repo.resolve()),
        "repo_name": repo.name,
        "number": number if number is not None else pr_number_from_subject(title),
        "title": title,
        "sha": sha,
        "short_sha": sha[:7],
        "committed_at": when.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "kind": kind,
        "url": url,
        "author_email": author_email,
        "author_login": None,
        "loc": loc,
    }


def first_author_email(repo: Path, parent: str, tip: str, sha: str) -> str | None:
    """E-mail de autor do primeiro commit do PR (o mais antigo que não é merge).

    No squash, o commit espremido leva o autor do PR. No merge e no rebase, o
    primeiro commit da branch indica quem abriu o trabalho.
    """
    listed = _git(repo, "log", "--reverse", "--no-merges", "--format=%ae", f"{parent}..{tip}")
    if listed.returncode == 0:
        for line in listed.stdout.splitlines():
            if line.strip():
                return line.strip().lower()
    own = _git(repo, "log", "-1", "--format=%ae", sha)
    if own.returncode == 0 and own.stdout.strip():
        return own.stdout.strip().lower()
    return None


def production_rev(repo: Path, branch: str) -> str:
    """Revisão de onde ler o que já está em produção.

    O ramo local pode estar semanas atrás. Se `origin/<ramo>` existe, é ele
    que vale. O nome curto do ramo continua sendo o que se pede ao GitHub.
    """
    if branch.startswith("origin/"):
        return branch
    remote = f"refs/remotes/origin/{branch}"
    if _git(repo, "rev-parse", "--verify", "--quiet", remote).returncode == 0:
        return f"origin/{branch}"
    return branch


def collect_git_prs(repo: Path, branch: str, start: dt.datetime, end: dt.datetime, cfg: dict) -> list[dict]:
    found = []
    for commit in iter_first_parent(repo, production_rev(repo, branch), start, end):
        if not is_shipped_commit(commit["subject"], commit["parents"]):
            continue
        record = pr_record(
            repo,
            commit["sha"],
            commit["when"],
            commit["parents"],
            commit["subject"],
            cfg,
        )
        if record:
            found.append(record)
    return found


def default_gh_items(repo: Path, branch: str, start: dt.datetime, end: dt.datetime) -> list[dict] | None:
    """Consulta o GitHub CLI. None significa que o gh não pôde ser usado."""
    try:
        listed = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "merged",
                "--base", branch,
                "--limit", "200",
                "--json", "number,title,mergedAt,mergeCommit,url,author",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None
    try:
        payload = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError:
        return None
    items = []
    for pr in payload:
        merged = parse_ts(pr.get("mergedAt"))
        sha = (pr.get("mergeCommit") or {}).get("oid")
        if merged is None or sha is None or merged < start or merged >= end:
            continue
        oids = _gh_commit_oids(repo, pr.get("number"))
        items.append({
            "number": pr.get("number"),
            "title": pr.get("title") or "",
            "merged_at": merged,
            "sha": sha,
            "url": pr.get("url"),
            "commit_oids": oids,
            "author_login": ((pr.get("author") or {}).get("login") or None),
        })
    return items


def _gh_commit_oids(repo: Path, number: int | None) -> list[str] | None:
    if not number:
        return None
    try:
        viewed = subprocess.run(
            ["gh", "pr", "view", str(number), "--json", "commits", "--jq", ".commits[].oid"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if viewed.returncode != 0:
        return None
    oids = [line.strip() for line in viewed.stdout.splitlines() if line.strip()]
    return oids or None


def merge_gh_items(
    repo: Path,
    branch: str,
    prs: list[dict],
    items: list[dict],
    cfg: dict,
) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    by_sha = {pr["sha"]: pr for pr in prs}
    for item in items:
        sha = item["sha"]
        if sha in by_sha:
            current = by_sha[sha]
            if current.get("number") is None and item.get("number") is not None:
                current["number"] = item["number"]
            if item.get("url"):
                current["url"] = item["url"]
            if item.get("title"):
                current["title"] = item["title"]
            if item.get("author_login"):
                current["author_login"] = item["author_login"]
            continue
        if not commit_exists(repo, sha):
            warnings.append(
                f"O PR #{item.get('number')} está mesclado no GitHub, mas o commit "
                f"{str(sha)[:7]} não está neste clone."
            )
            continue
        if not is_ancestor(repo, sha, production_rev(repo, branch)):
            warnings.append(
                f"O PR #{item.get('number')} não está no ramo {branch} deste clone."
            )
            continue
        when, parents, subject = commit_meta(repo, sha)
        if when is None:
            continue
        title = item.get("title") or subject
        record = pr_record(
            repo,
            sha,
            when,
            parents,
            title,
            cfg,
            number=item.get("number"),
            url=item.get("url"),
            oids=item.get("commit_oids"),
            kind="github",
        )
        if record:
            record["author_login"] = item.get("author_login")
            prs.append(record)
            by_sha[sha] = record
    return prs, warnings


NOREPLY = re.compile(r"^(?:\d+\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$")


def gh_user_login() -> str | None:
    """Login do GitHub CLI autenticado (`gh api user`). None se não houver."""
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    login = result.stdout.strip()
    if result.returncode != 0 or not login:
        return None
    return login


def git_user_email(path: Path | None = None) -> str | None:
    args = ["git"]
    if path is not None:
        args += ["-C", str(path)]
    args += ["config", "user.email"]
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    email = result.stdout.strip().lower()
    return email or None


def resolve_identity(
    cfg: dict,
    cli_authors: list[str] | None,
    use_gh: bool,
    repos: list[Path],
    login_fetcher=None,
) -> dict:
    """Quem é "você" na conta. Login do GitHub e/ou e-mail de commit.

    Prioridade: --autor; senão a lista `autores` do config; o que faltar vem
    do `gh api user` (login) e do `git config user.email` (e-mail).
    """
    logins: set[str] = set()
    emails: set[str] = set()
    sources: list[str] = []
    for item in cli_authors or []:
        value = item.strip().lower()
        if not value:
            continue
        (emails if "@" in value else logins).add(value)
    if logins or emails:
        sources.append("--autor")
        return {"logins": sorted(logins), "emails": sorted(emails), "sources": sources}
    configured = cfg.get("autores") or {}
    for value in configured.get("logins") or []:
        if str(value).strip():
            logins.add(str(value).strip().lower())
    for value in configured.get("emails") or []:
        if str(value).strip():
            emails.add(str(value).strip().lower())
    if logins or emails:
        sources.append("rot_config.json")
    if not logins and use_gh:
        login = (login_fetcher or gh_user_login)()
        if login:
            logins.add(login.lower())
            sources.append("gh api user")
    if not emails:
        for repo in repos:
            email = git_user_email(repo)
            if email:
                emails.add(email)
        if not emails:
            email = git_user_email(None)
            if email:
                emails.add(email)
        if emails:
            sources.append("git config user.email")
    return {"logins": sorted(logins), "emails": sorted(emails), "sources": sources}


def pr_is_mine(pr: dict, identity: dict) -> bool:
    """O PR é seu se o login do autor no GitHub casa; sem login, vale o e-mail.

    Login conhecido e diferente do seu decide "não", mesmo que o e-mail case:
    o GitHub sabe quem abriu o PR. E-mail noreply do GitHub
    (123+login@users.noreply.github.com) conta como o login.
    """
    logins = set(identity.get("logins") or [])
    emails = set(identity.get("emails") or [])
    login = (pr.get("author_login") or "").lower()
    if login and logins:
        return login in logins
    email = (pr.get("author_email") or "").lower()
    if not email:
        return False
    if email in emails:
        return True
    match = NOREPLY.match(email)
    return bool(match and match.group("login").lower() in logins)


def pr_author_label(pr: dict) -> str:
    return pr.get("author_login") or pr.get("author_email") or "desconhecido"



DATE_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<date>20\d{6})$")
TOKEN_TYPES = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


def model_aliases(cfg: dict) -> dict[str, str]:
    """Apelidos explícitos do config: nome exato no log → nome exato na tabela."""
    raw = cfg.get("model_aliases") or {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if not str(key).startswith("_") and isinstance(value, str)
    }


def resolve_model_name(cfg: dict, model: str) -> str | None:
    """Casa o modelo com a tabela só por nome exato.

    Ordem: nome exato; apelido exato em model_aliases; e, por último, o nome
    sem um sufixo de data de 8 dígitos (-AAAAMMDD) quando a tabela lista o
    nome base. Não há prefixo, parente mais próximo nem outro palpite: o que
    não casar fica sem preço.
    """
    models = public_dict(cfg.get("models", {}))
    if model in models:
        return model
    alias = model_aliases(cfg).get(model)
    if alias is not None and alias in models:
        return alias
    match = DATE_SUFFIX.match(model)
    if match and match.group("base") in models:
        return match.group("base")
    return None


def lookup_rate(cfg: dict, model: str) -> dict | None:
    name = resolve_model_name(cfg, model)
    if name is None:
        return None
    return public_dict(cfg.get("models", {}))[name]


def price_breakdown(cfg: dict, model: str, incoming: int, outgoing: int, cache_5m: int, cache_1h: int, cache_read: int) -> dict | None:
    """Custo em dólares por tipo de token. None quando o modelo não tem preço."""
    rate = lookup_rate(cfg, model)
    if rate is None:
        return None
    prompt = incoming + cache_5m + cache_1h + cache_read
    over = rate.get("when_prompt_over_100k_tokens")
    if isinstance(over, dict) and prompt > 100_000:
        rate = over
    try:
        return {
            "input": incoming * float(rate["input"]) / 1_000_000.0,
            "output": outgoing * float(rate["output"]) / 1_000_000.0,
            "cache_write_5m": cache_5m * float(rate["cache_write_5m"]) / 1_000_000.0,
            "cache_write_1h": cache_1h * float(rate["cache_write_1h"]) / 1_000_000.0,
            "cache_read": cache_read * float(rate["cache_read"]) / 1_000_000.0,
        }
    except (KeyError, TypeError, ValueError):
        return None


def price_turn(cfg: dict, model: str, incoming: int, outgoing: int, cache_5m: int, cache_1h: int, cache_read: int) -> tuple[float, str | None]:
    parts = price_breakdown(cfg, model, incoming, outgoing, cache_5m, cache_1h, cache_read)
    if parts is None:
        return 0.0, model
    return sum(parts.values()), None


def empty_tokens() -> dict:
    return {
        "input": 0,
        "output": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": 0,
        "api_cost_usd": 0.0,
        "cost_by_type_usd": {key: 0.0 for key in TOKEN_TYPES},
        "unpriced_by_type": {key: 0 for key in TOKEN_TYPES},
        "by_model_tokens": {},
        "by_model_cost_usd": {},
        "unpriced_tokens": {},
    }


def token_total(bucket: dict) -> int:
    return (
        bucket["input"] + bucket["output"] + bucket["cache_write_5m"]
        + bucket["cache_write_1h"] + bucket["cache_read"]
    )


def add_tokens(total: dict, part: dict, scale: float = 1.0) -> None:
    for key in ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read"):
        total[key] += part[key] * scale
    total["api_cost_usd"] += part["api_cost_usd"] * scale
    for key in TOKEN_TYPES:
        total["cost_by_type_usd"][key] += part["cost_by_type_usd"][key] * scale
        total["unpriced_by_type"][key] += part["unpriced_by_type"][key] * scale
    for model, amount in part["by_model_tokens"].items():
        total["by_model_tokens"][model] = total["by_model_tokens"].get(model, 0) + amount * scale
    for model, amount in part["by_model_cost_usd"].items():
        total["by_model_cost_usd"][model] = total["by_model_cost_usd"].get(model, 0.0) + amount * scale
    for model, amount in part["unpriced_tokens"].items():
        total["unpriced_tokens"][model] = total["unpriced_tokens"].get(model, 0) + amount * scale


def cache_split(usage: dict) -> tuple[int, int]:
    """O detalhe de 5 min / 1 h prevalece. O inteiro agregado não é somado de novo."""
    detail = usage.get("cache_creation")
    if isinstance(detail, dict):
        cache_5m = int(detail.get("ephemeral_5m_input_tokens") or 0)
        cache_1h = int(detail.get("ephemeral_1h_input_tokens") or 0)
        if cache_5m or cache_1h:
            return cache_5m, cache_1h
    return int(usage.get("cache_creation_input_tokens") or 0), 0


def usage_from_record(record: dict) -> dict | None:
    message = record.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        usage = message["usage"]
        model = message.get("model") or record.get("model") or "desconhecido"
        return {"usage": usage, "model": str(model)}
    if isinstance(record.get("usage"), dict):
        return {"usage": record["usage"], "model": str(record.get("model") or "desconhecido")}
    return None


def text_of_user(record: dict) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text") or ""))
        return "\n".join(chunks)
    return ""


def usage_numbers(usage: dict) -> dict:
    cache_5m, cache_1h = cache_split(usage)
    return {
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "cache_write_5m": cache_5m,
        "cache_write_1h": cache_1h,
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
    }


def apply_numbers(bucket: dict, cfg: dict, model: str, numbers: dict) -> None:
    parts = price_breakdown(
        cfg, model,
        numbers["input"], numbers["output"], numbers["cache_write_5m"],
        numbers["cache_write_1h"], numbers["cache_read"],
    )
    mass = sum(numbers[key] for key in TOKEN_TYPES)
    for key in TOKEN_TYPES:
        bucket[key] += numbers[key]
    bucket["by_model_tokens"][model] = bucket["by_model_tokens"].get(model, 0) + mass
    if parts is None:
        bucket["by_model_cost_usd"][model] = bucket["by_model_cost_usd"].get(model, 0.0)
        if mass:
            bucket["unpriced_tokens"][model] = bucket["unpriced_tokens"].get(model, 0) + mass
            for key in TOKEN_TYPES:
                bucket["unpriced_by_type"][key] += numbers[key]
        return
    usd = sum(parts.values())
    for key in TOKEN_TYPES:
        bucket["cost_by_type_usd"][key] += parts[key]
    bucket["api_cost_usd"] += usd
    bucket["by_model_cost_usd"][model] = bucket["by_model_cost_usd"].get(model, 0.0) + usd


def apply_usage(bucket: dict, cfg: dict, model: str, usage: dict) -> None:
    apply_numbers(bucket, cfg, model, usage_numbers(usage))


def usage_key(record: dict) -> tuple | None:
    """Identidade de uma resposta do assistente no log.

    O Claude Code grava a mesma resposta várias vezes: um registro por bloco
    de conteúdo durante o streaming, cópias quando a sessão é retomada e
    cópias em sidechains. Todas trazem o mesmo message.id e o mesmo
    requestId. Sem nenhum dos dois, o uuid do registro serve de chave; sem
    nada, o registro conta sozinho.
    """
    message = record.get("message")
    message_id = message.get("id") if isinstance(message, dict) else None
    request_id = record.get("requestId")
    if message_id or request_id:
        return ("msg", str(message_id or ""), str(request_id or ""))
    if record.get("uuid"):
        return ("uuid", str(record["uuid"]))
    return None


def merge_numbers(current: dict, new: dict) -> dict:
    """Fica o maior valor de cada campo: o registro final do streaming é o completo."""
    return {key: max(current[key], new[key]) for key in TOKEN_TYPES}


def scan_projects(projects_dir: Path, cfg: dict, start: dt.datetime, end: dt.datetime) -> tuple[list[dict], list[str], dict]:
    """Lê os JSONL e devolve sessões, avisos e a contagem de deduplicação."""
    warnings: list[str] = []
    stats = {"records": 0, "unique": 0, "duplicates": 0, "duplicate_files": 0, "untimed": 0}
    if not projects_dir.is_dir():
        warnings.append(f"Não encontrei logs do Claude Code em {projects_dir}.")
        return [], warnings, stats
    files: list[dict] = []
    seen_hashes: set[str] = set()
    # chave → {"file": índice, "moment", "model", "numbers"}
    unique: dict[tuple, dict] = {}
    loose: list[dict] = []
    untimed_keys: set[tuple] = set()
    untimed_loose = 0
    for path in sorted(projects_dir.rglob("*.jsonl")):
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            warnings.append(f"Não consegui ler {path.name}: {exc}")
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_hashes:
            stats["duplicate_files"] += 1
            continue
        seen_hashes.add(digest)
        info = {"path": path, "cwd": None, "session_id": None, "mentions": set()}
        index = len(files)
        files.append(info)
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("cwd"):
                info["cwd"] = str(record["cwd"])
            if record.get("sessionId"):
                info["session_id"] = str(record["sessionId"])
            moment = parse_ts(record.get("timestamp"))
            found = usage_from_record(record)
            if not found:
                if record.get("type") == "user" and moment is not None and start <= moment < end:
                    for number in PR_MENTION.findall(text_of_user(record)):
                        info["mentions"].add(int(number))
                continue
            stats["records"] += 1
            key = usage_key(record)
            numbers = usage_numbers(found["usage"])
            if key is None:
                if moment is None:
                    untimed_loose += 1
                    continue
                loose.append({"file": index, "moment": moment, "model": found["model"], "numbers": numbers})
                continue
            entry = unique.get(key)
            if entry is None:
                unique[key] = {"file": index, "moment": moment, "model": found["model"], "numbers": numbers}
                continue
            stats["duplicates"] += 1
            entry["numbers"] = merge_numbers(entry["numbers"], numbers)
            if entry["model"] == "desconhecido" and found["model"] != "desconhecido":
                entry["model"] = found["model"]
            if moment is not None and (entry["moment"] is None or moment < entry["moment"]):
                entry["moment"] = moment
    stats["unique"] = len(unique) + len(loose)
    per_file: dict[int, dict] = {}
    for key, entry in list(unique.items()) + [(None, item) for item in loose]:
        moment = entry["moment"]
        if moment is None:
            untimed_keys.add(key)
            continue
        if moment < start or moment >= end:
            continue
        slot = per_file.setdefault(entry["file"], {"bucket": empty_tokens(), "moments": []})
        apply_numbers(slot["bucket"], cfg, entry["model"], entry["numbers"])
        slot["moments"].append(moment)
    untimed = len(untimed_keys) + untimed_loose
    sessions = []
    root_cache: dict[str, Path | None] = {}
    for index in sorted(per_file):
        info = files[index]
        slot = per_file[index]
        root = find_git_root(info["cwd"], root_cache)
        sessions.append({
            "path": str(info["path"]),
            "session_id": info["session_id"] or info["path"].stem,
            "cwd": info["cwd"],
            "git_root": str(root) if root else None,
            "start": min(slot["moments"]).isoformat(),
            "end": max(slot["moments"]).isoformat(),
            "mentions": sorted(info["mentions"]),
            "tokens": slot["bucket"],
        })
    if untimed == 1:
        warnings.append(
            "1 evento com tokens sem data confiável (fuso ausente ou inválido) foi ignorado."
        )
    elif untimed:
        warnings.append(
            f"{format_int(untimed)} eventos com tokens sem data confiável (fuso ausente ou inválido) foram ignorados."
        )
    if not sessions and not warnings:
        warnings.append(f"Nenhum token do Claude Code caiu neste período em {projects_dir}.")
    stats["untimed"] = untimed
    return sessions, warnings, stats


SESSION_LOOKBACK = dt.timedelta(days=2)


def overlaps(start_a: dt.datetime, end_a: dt.datetime, start_b: dt.datetime, end_b: dt.datetime) -> bool:
    return start_a <= end_b and start_b <= end_a


def attribute_sessions(sessions: list[dict], prs: list[dict]) -> None:
    """Reparte tokens de uma sessão entre PRs do mesmo repositório.

    Prioridade: número citado no prompt; senão, sobreposição com a janela do
    PR. O que não casa fica no repositório, sem PR. O total do período não
    depende dessa heurística.
    """
    for pr in prs:
        pr["attributed_tokens"] = empty_tokens()
    for session in sessions:
        root = session.get("git_root")
        if not root:
            continue
        candidates = [pr for pr in prs if pr["repo_path"] == root]
        mentioned = [
            pr for pr in candidates
            if pr.get("number") is not None and pr["number"] in session["mentions"]
        ]
        if mentioned:
            chosen = mentioned
        else:
            start = parse_ts(session["start"])
            end = parse_ts(session["end"])
            chosen = []
            if start and end:
                for pr in candidates:
                    pr_start = parse_ts(pr["window_start"])
                    pr_end = parse_ts(pr["window_end"])
                    if pr_start and pr_end and overlaps(start, end, pr_start, pr_end):
                        chosen.append(pr)
        if not chosen:
            continue
        scale = 1.0 / len(chosen)
        for pr in chosen:
            add_tokens(pr["attributed_tokens"], session["tokens"], scale)


def sum_sessions(sessions: list[dict], predicate=None) -> dict:
    total = empty_tokens()
    for session in sessions:
        if predicate and not predicate(session):
            continue
        add_tokens(total, session["tokens"])
    return total


def round_token_bucket(bucket: dict) -> dict:
    rounded = {
        "input": int(round(bucket["input"])),
        "output": int(round(bucket["output"])),
        "cache_write_5m": int(round(bucket["cache_write_5m"])),
        "cache_write_1h": int(round(bucket["cache_write_1h"])),
        "cache_read": int(round(bucket["cache_read"])),
        "total": int(round(token_total(bucket))),
        "api_cost_usd": bucket["api_cost_usd"],
        "cost_by_type_usd": {key: bucket["cost_by_type_usd"][key] for key in TOKEN_TYPES},
        "unpriced_by_type": {key: int(round(bucket["unpriced_by_type"][key])) for key in TOKEN_TYPES},
        "unpriced_total": int(round(sum(bucket["unpriced_by_type"].values()))),
        "by_model_tokens": {
            key: int(round(value)) for key, value in sorted(bucket["by_model_tokens"].items(), key=lambda item: -item[1])
        },
        "by_model_cost_usd": {
            key: value for key, value in sorted(bucket["by_model_cost_usd"].items(), key=lambda item: -item[1])
        },
        "unpriced_tokens": {
            key: int(round(value))
            for key, value in sorted(bucket["unpriced_tokens"].items(), key=lambda item: -item[1])
        },
    }
    return rounded


def prorate(monthly_usd: float, period_id: str, month_days: float) -> float:
    days = PERIODS[period_id].total_seconds() / 86400.0
    return monthly_usd * (days / month_days)


def plan_spec(cfg: dict, plan_id: str, monthly_usd: float | None, label: str | None) -> dict:
    if plan_id == "custom":
        if monthly_usd is None:
            raise ValueError("custom-sem-mensalidade")
        return {
            "id": "custom",
            "label": label or "Outro plano",
            "kind": "subscription",
            "monthly_usd": float(monthly_usd),
        }
    plans = public_dict(cfg.get("plans", {}))
    if plan_id not in plans:
        raise ValueError(plan_id)
    plan = plans[plan_id]
    return {
        "id": plan_id,
        "label": label or plan.get("label") or plan_id,
        "kind": plan.get("kind") or "subscription",
        "monthly_usd": float(plan.get("monthly_usd") or 0),
    }


def ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def build_caveats(report: dict) -> list[str]:
    caveats = [
        "Linha efetiva é, por arquivo de texto, o maior valor entre adições e remoções. Uma refatoração que troca 100 linhas por 100 conta 100 — não 200 e não zero. Arquivos diferentes não se cancelam.",
        "Entram mudanças que chegaram ao ramo de produção por commit de merge ou por assunto de pull request (Merge pull request #N ou sufixo (#N)). Commit direto, sem PR, fica de fora. Rebase sem número no assunto só entra se o GitHub CLI informar o PR.",
        "Lockfile, código vendorizado, arquivo gerado e snapshot saem da conta pelo caminho. Um gerado com nome fora da lista entra. As listas estão em rot_config.json.",
        "Os tokens vêm só dos JSONL locais do Claude Code nesta máquina. Conversa na web, outro aplicativo e log apagado não aparecem.",
        "O custo da assinatura é a mensalidade proporcional ao período (mês de 30,4375 dias, que é 365,25/12). É um custo fixo rateado, não a causa das linhas: quanto mais código entra em produção, menor fica o custo por linha.",
        "O equivalente de API usa a tabela publicada e editável, e só casa o nome exato do modelo (ou um apelido exato em model_aliases, ou o nome sem sufixo de data -AAAAMMDD quando a tabela lista o nome base). Modelo sem linha fica sem preço: os tokens aparecem à parte e não entram no dólar. Gravação de cache sem o detalhe de 5 minutos ou 1 hora é cobrada como 5 minutos.",
        "O Claude Code grava a mesma resposta várias vezes (streaming, sessão retomada, sidechain). Cada resposta conta uma vez, pela dupla message.id + requestId, com o maior uso registrado.",
        "Só entram PRs de sua autoria: login do GitHub quando o gh informa o autor, senão o e-mail do primeiro commit do PR. PRs de colegas mesclados no mesmo ramo ficam fora e aparecem só como contagem.",
        "Linhas por milhão de tokens de saída é uma razão de volume, não de qualidade. Ela ignora entrada e cache, que dependem do tamanho do contexto e não do código produzido.",
        "Atribuição de token a um PR é heurística (pasta da sessão, menção ao número, janela do PR). O total do período é a medida firme.",
        "Isto não é ROI de negócio. Não estima salário, hora economizada, receita nem risco.",
    ]
    if report["cost"]["usd_brl_rate"]:
        checked = report["cost"].get("usd_brl_checked") or "a data anotada no config"
        caveats.append(
            f"O real usa a taxa editável de {format_number(report['cost']['usd_brl_rate'], 4)} reais por dólar "
            f"({checked}). Não é cotação ao vivo. O dólar continua sendo a moeda base."
        )
    if report["plan"]["id"] == "custom":
        caveats.append(
            "No plano custom, os tokens lidos continuam sendo só do Claude Code. O uso de outra ferramenta não entra no equivalente de API."
        )
    return caveats


def unpriced_warnings(bucket: dict) -> list[str]:
    warnings = []
    for model, amount in bucket["unpriced_tokens"].items():
        warnings.append(
            f"!! ATENÇÃO: o modelo '{model}' não tem preço em rot_config.json. "
            f"{format_int(amount)} tokens SEM PREÇO ficaram fora do custo — o equivalente de API está subestimado. "
            "Acrescente o modelo à tabela, ou um apelido exato em model_aliases."
        )
    return warnings


TOKEN_LABELS = (
    ("input", "Entrada"),
    ("output", "Saída"),
    ("cache_write_5m", "Gravação de cache (5 min)"),
    ("cache_write_1h", "Gravação de cache (1 h)"),
    ("cache_read", "Leitura de cache"),
)


def excluded_phrase(loc: dict) -> str:
    labels = {
        "lockfile": "lockfiles",
        "vendored": "código vendorizado",
        "generated": "arquivos gerados",
        "snapshot": "snapshots",
    }
    parts = []
    for key, label in labels.items():
        lines = loc["excluded"][key]["lines"]
        if lines:
            parts.append(f"{format_int(lines)} em {label}")
    if not parts:
        return "nada"
    return ", ".join(parts)


def plural(count: int, one: str, many: str) -> str:
    return f"{format_int(count)} {one if count == 1 else many}"


def render_text(report: dict) -> str:
    lines: list[str] = []
    period = report["period"]
    plan = report["plan"]
    tokens = report["tokens"]
    loc = report["loc"]
    cost = report["cost"]
    ratios = report["ratios"]
    lines.append("=" * 72)
    lines.append("  ROT — Retorno sobre Tokens")
    lines.append(f"  {period['label']} · {format_dt(parse_ts(period['start']))} → {format_dt(parse_ts(period['end']))}")
    monthly = format_usd(plan["monthly_usd"]) + "/mês" if plan["kind"] == "subscription" else "paga por token"
    lines.append(f"  Plano: {plan['label']} · {monthly}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("TOKENS")
    lines.append(f"  Logs em {report['projects_dir']}")
    lines.append(f"  {'Tipo':<26}{'Tokens':>14}{'Custo API':>16}{'% do custo':>12}")
    api_total = tokens["api_cost_usd"]
    for key, label in TOKEN_LABELS:
        share = tokens["cost_by_type_usd"][key] / api_total * 100 if api_total else 0.0
        lines.append(
            f"  {label:<26}{format_int(tokens[key]):>14}"
            f"{format_usd(tokens['cost_by_type_usd'][key]):>16}{format_number(share, 1) + '%':>12}"
        )
    lines.append(f"  {'Total':<26}{format_int(tokens['total']):>14}{format_usd(api_total):>16}")
    if tokens["unpriced_total"]:
        lines.append(f"  {'Sem preço (fora do custo)':<26}{format_int(tokens['unpriced_total']):>14}")
    lines.append(f"  {'Sessões no período':<26}{format_int(report['sessions']):>14}")
    dedup = report.get("dedup") or {}
    if dedup.get("duplicates") or dedup.get("duplicate_files"):
        lines.append(
            f"  Duplicatas descartadas: {plural(dedup.get('duplicates', 0), 'registro repetido', 'registros repetidos')}"
            f" e {plural(dedup.get('duplicate_files', 0), 'arquivo idêntico', 'arquivos idênticos')}."
        )
    lines.append("")
    lines.append("CÓDIGO EM PRODUÇÃO")
    if not report["pull_requests"]:
        lines.append("  Nenhum pull request chegou à produção neste período.")
    for repo in report["repos"]:
        repo_prs = [pr for pr in report["pull_requests"] if pr["repo_path"] == repo["path"]]
        lines.append(f"  {repo['name']} · ramo {repo['branch']} · fonte: {repo['source']}")
        if not repo_prs:
            lines.append("    Nenhum PR mesclado neste período.")
            continue
        for pr in repo_prs:
            number = f"PR #{pr['number']}" if pr["number"] is not None else "mesclagem local"
            loc_pr = pr["loc"]
            lines.append(
                f"    {number:<12} {pr['short_sha']}  "
                f"{format_int(loc_pr['effective'])} linhas efetivas  "
                f"(+{format_int(loc_pr['additions'])} −{format_int(loc_pr['deletions'])}, "
                f"saldo {format_signed_int(loc_pr['additions'] - loc_pr['deletions'])})"
            )
            lines.append(f"      {pr['title']}")
    lines.append("")
    lines.append(f"  {'Linhas efetivas':<32}{format_int(loc['effective']):>14}")
    lines.append(f"  {'Adições':<32}{format_int(loc['additions']):>14}")
    lines.append(f"  {'Remoções':<32}{format_int(loc['deletions']):>14}")
    lines.append(f"  {'Saldo':<32}{format_signed_int(loc['additions'] - loc['deletions']):>14}")
    lines.append(f"  Fora da conta (adições + remoções): {excluded_phrase(loc)}.")
    if loc["binary_files"]:
        lines.append(f"  Binários ignorados: {format_int(loc['binary_files'])}.")
    identity = report.get("identity") or {}
    who = ", ".join((identity.get("logins") or []) + (identity.get("emails") or [])) or "ninguém"
    lines.append(f"  Autor considerado: {who} (fonte: {', '.join(identity.get('sources') or ['nenhuma'])}).")
    others = report.get("other_authors") or {}
    if others.get("pull_requests"):
        lines.append(
            f"  PRs de outros autores fora da conta: {format_int(others['pull_requests'])} "
            f"({plural(others['effective'], 'linha efetiva', 'linhas efetivas')}, "
            f"{plural(len(others['authors']), 'autor', 'autores')})."
        )
    without = report.get("without_session")
    if without and without.get("pull_requests"):
        lines.append(
            f"  PRs sem sessão do Claude Code no repositório: {format_int(without['pull_requests'])} "
            f"({format_int(without['effective'])} linhas efetivas) ficaram fora."
        )
    lines.append("")
    lines.append("CUSTO")
    lines.append(f"  {'Equivalente de API':<32}{format_usd(cost['api_equivalent_usd']):>18}")
    if plan["kind"] == "subscription":
        lines.append(
            "    Se estes tokens fossem cobrados pela API (preço de lista), "
            f"custaria {format_usd(cost['api_equivalent_usd'])}"
            + (f" ({format_brl(cost['api_equivalent_brl'])})." if cost.get("api_equivalent_brl") else ".")
        )
    else:
        lines.append("    Este plano já cobra o preço de lista da API.")
    if plan["kind"] == "subscription":
        lines.append(f"  {'Assinatura proporcional':<32}{format_usd(cost['subscription_prorated_usd']):>18}")
        lines.append(
            f"    {format_usd(plan['monthly_usd'])} × {period['days_label']}/{format_number(cost['month_days'], 4)} dias"
        )
    lines.append(f"  {'Custo usado nos indicadores':<32}{format_usd(cost['primary_usd']):>18}")
    if plan["kind"] == "subscription":
        lines.append("    Caixa da assinatura neste período, não o preço de tabela da API.")
    else:
        lines.append("    Preço de tabela da API sobre os tokens lidos.")
    if cost["usd_brl_rate"]:
        lines.append(
            f"  {'Em reais':<32}{format_brl(cost['primary_brl']):>18}"
        )
        lines.append(
            f"    US$ 1 = {format_brl(cost['usd_brl_rate'], 4)}. Câmbio editável em rot_config.json."
        )
        lines.append(f"    Equivalente de API em reais: {format_brl(cost['api_equivalent_brl'])}.")
    lines.append("")
    lines.append("INDICADORES")
    lines.append(f"  {'Custo por linha efetiva':<52}{_fmt_optional_usd(ratios['usd_per_effective_loc'])}")
    if cost["usd_brl_rate"]:
        lines.append(f"  {'O mesmo em reais':<52}{_fmt_optional_brl(ratios['brl_per_effective_loc'])}")
    lines.append(f"  {'Equivalente de API por linha efetiva':<52}{_fmt_optional_usd(ratios['api_usd_per_effective_loc'])}")
    lines.append(
        f"  {'Linhas efetivas por milhão de tokens de SAÍDA':<52}"
        f"{_fmt_optional_number(ratios['effective_loc_per_million_output_tokens'])}"
    )
    if report["by_repo"]:
        lines.append("")
        lines.append("POR REPOSITÓRIO")
        for repo in report["by_repo"]:
            lines.append(
                f"  {repo['name']}: {format_int(repo['effective'])} linhas efetivas, "
                f"{format_int(repo['tokens'])} tokens na pasta, "
                f"API {format_usd(repo['api_cost_usd'])}"
            )
    if report["warnings"]:
        lines.append("")
        lines.append("AVISOS")
        for warning in report["warnings"]:
            lines.append(f"  {warning}" if warning.startswith("!") else f"  ! {warning}")
    lines.append("")
    lines.append("RESSALVAS")
    for caveat in report["caveats"]:
        lines.append(f"  - {caveat}")
    lines.append("=" * 72)
    return "\n".join(lines)


def _fmt_optional_usd(value: float | None) -> str:
    if value is None:
        return "não se aplica"
    return format_usd(value)


def _fmt_optional_brl(value: float | None) -> str:
    if value is None:
        return "não se aplica"
    return format_brl(value)


def _fmt_optional_number(value: float | None) -> str:
    if value is None:
        return "não se aplica"
    return format_number(value, 2)


def _repo_list(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    cache: dict[str, Path | None] = {}
    for path in paths:
        root = find_git_root(str(path), cache)
        if root is None and path.exists() and _git(path, "rev-parse", "--is-inside-work-tree").returncode == 0:
            root = main_worktree(path)
        if root is None:
            continue
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(root)
    return found


def analyze(
    *,
    now: dt.datetime,
    period_id: str,
    plan: dict,
    repos: list[Path],
    projects_dir: Path,
    config: dict,
    use_gh: bool = True,
    gh_fetcher=None,
    branch: str | None = None,
    exchange_rate: float | None = None,
    include_cwd: bool = False,
    authors: list[str] | None = None,
    identity: dict | None = None,
    login_fetcher=None,
    require_session: bool = False,
) -> dict:
    start, end = period_bounds(period_id, now)
    sessions, warnings, dedup_stats = scan_projects(projects_dir, config, start, end)
    repo_inputs = list(repos)
    if include_cwd:
        repo_inputs.append(Path.cwd())
    for session in sessions:
        if session.get("git_root"):
            repo_inputs.append(Path(session["git_root"]))
    root_cache: dict[str, Path | None] = {}
    for path in repos:
        if find_git_root(str(path), root_cache) is None:
            warnings.append(f"{path} não é um repositório git.")
    resolved = _repo_list(repo_inputs)
    if identity is None:
        identity = resolve_identity(config, authors, use_gh, resolved, login_fetcher)
    if not identity["logins"] and not identity["emails"]:
        warnings.append(
            "!! Não sei quem é você: sem --autor, sem `autores` no config, sem `gh api user` e sem "
            "`git config user.email`. Nenhum PR foi contado. Rode de novo com --autor SEU_LOGIN."
        )
    other_authors = {"pull_requests": 0, "effective": 0, "additions": 0, "deletions": 0, "authors": []}
    without_session = {"pull_requests": 0, "effective": 0}
    other_labels: set[str] = set()
    configured_branch = (config.get("production_branch") or "").strip() or None
    month_days = float(config.get("month_days") or MONTH_DAYS_DEFAULT)
    pull_requests: list[dict] = []
    repo_rows = []
    for repo in resolved:
        chosen_branch = branch or detect_default_branch(repo, configured_branch if not branch else None)
        source = "git"
        try:
            prs = collect_git_prs(repo, chosen_branch, start, end, config)
        except RuntimeError as exc:
            warnings.append(f"Não consegui ler o ramo {chosen_branch} em {repo.name}: {exc}")
            repo_rows.append({
                "name": repo.name,
                "path": str(repo),
                "branch": chosen_branch,
                "source": source,
            })
            continue
        if use_gh:
            fetcher = gh_fetcher or default_gh_items
            try:
                items = fetcher(repo, chosen_branch, start, end)
            except Exception as exc:  # falha do gh não pode derrubar o relatório
                warnings.append(f"GitHub CLI falhou em {repo.name}: {exc}")
                items = None
            if items is None:
                warnings.append(
                    f"GitHub CLI indisponível em {repo.name}; os PRs foram identificados só pelo git."
                )
            else:
                prs, gh_warnings = merge_gh_items(repo, chosen_branch, prs, items, config)
                warnings.extend(gh_warnings)
                source = "git+github"
        prs.sort(key=lambda item: item["committed_at"])
        mine = []
        for pr in prs:
            if pr_is_mine(pr, identity):
                mine.append(pr)
                continue
            other_authors["pull_requests"] += 1
            other_authors["effective"] += pr["loc"]["effective"]
            other_authors["additions"] += pr["loc"]["additions"]
            other_authors["deletions"] += pr["loc"]["deletions"]
            other_labels.add(pr_author_label(pr))
        pull_requests.extend(mine)
        repo_rows.append({
            "name": repo.name,
            "path": str(repo),
            "branch": chosen_branch,
            "source": source,
        })

    if require_session:
        # Um PR squash tem janela de um instante só (o commit no ramo). O
        # trabalho vem antes, então a janela ganha SESSION_LOOKBACK para trás.
        kept = []
        for pr in pull_requests:
            window_start = parse_ts(pr["window_start"]) - SESSION_LOOKBACK
            window_end = parse_ts(pr["window_end"])
            touched = any(
                session.get("git_root") == pr["repo_path"]
                and overlaps(parse_ts(session["start"]), parse_ts(session["end"]), window_start, window_end)
                for session in sessions
            )
            if touched:
                kept.append(pr)
            else:
                without_session["pull_requests"] += 1
                without_session["effective"] += pr["loc"]["effective"]
        pull_requests = kept
    other_authors["authors"] = sorted(other_labels)
    attribute_sessions(sessions, pull_requests)
    period_tokens = sum_sessions(sessions)
    loc = empty_loc()
    for pr in pull_requests:
        add_loc(loc, pr["loc"])
    shipping_roots = {pr["repo_path"] for pr in pull_requests}
    shipping_tokens = sum_sessions(sessions, lambda session: session.get("git_root") in shipping_roots)

    rate = exchange_rate
    if rate is None:
        raw_rate = config.get("usd_brl")
        rate = float(raw_rate) if raw_rate else 0.0
    if rate <= 0:
        rate = 0.0

    api_usd = period_tokens["api_cost_usd"]
    subscription_usd = 0.0
    if plan["kind"] == "subscription":
        subscription_usd = prorate(plan["monthly_usd"], period_id, month_days)
        primary = subscription_usd
        basis = "subscription"
    else:
        primary = api_usd
        basis = "api"

    def money_brl(usd: float) -> float | None:
        if not rate:
            return None
        return usd * rate

    days = PERIODS[period_id].total_seconds() / 86400.0
    days_label = format_number(days, 0 if days == int(days) else 2)
    token_view = round_token_bucket(period_tokens)
    shipping_view = round_token_bucket(shipping_tokens)
    effective = loc["effective"]
    report = {
        "period": {
            "id": period_id,
            "label": PERIOD_LABELS[period_id],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days_label": days_label,
        },
        "plan": plan,
        "projects_dir": str(projects_dir),
        "sessions": len(sessions),
        "tokens": token_view,
        "shipping_tokens": shipping_view,
        "loc": loc,
        "pull_requests": pull_requests,
        "repos": repo_rows,
        "cost": {
            "api_equivalent_usd": api_usd,
            "subscription_prorated_usd": subscription_usd,
            "primary_usd": primary,
            "primary_basis": basis,
            "month_days": month_days,
            "usd_brl_rate": rate,
            "usd_brl_checked": config.get("usd_brl_checked"),
            "api_equivalent_brl": money_brl(api_usd),
            "subscription_prorated_brl": money_brl(subscription_usd) if plan["kind"] == "subscription" else None,
            "primary_brl": money_brl(primary),
            "pricing_source": config.get("pricing_source"),
            "pricing_checked": config.get("pricing_checked"),
        },
        "ratios": {
            "usd_per_effective_loc": ratio(primary, effective),
            "brl_per_effective_loc": ratio(money_brl(primary) or 0.0, effective) if rate and effective else None,
            "api_usd_per_effective_loc": ratio(api_usd, effective),
            "effective_loc_per_million_output_tokens": (
                ratio(effective, token_view["output"] / 1_000_000) if token_view["output"] else None
            ),
        },
        "identity": identity,
        "other_authors": other_authors,
        "without_session": without_session if require_session else None,
        "dedup": dedup_stats,
        "by_repo": [],
        "warnings": [],
        "caveats": [],
    }
    by_repo = []
    for repo in repo_rows:
        repo_prs = [pr for pr in pull_requests if pr["repo_path"] == repo["path"]]
        repo_loc = empty_loc()
        for pr in repo_prs:
            add_loc(repo_loc, pr["loc"])
        repo_tokens = sum_sessions(sessions, lambda session, path=repo["path"]: session.get("git_root") == path)
        by_repo.append({
            "name": repo["name"],
            "path": repo["path"],
            "effective": repo_loc["effective"],
            "additions": repo_loc["additions"],
            "deletions": repo_loc["deletions"],
            "tokens": int(round(token_total(repo_tokens))),
            "api_cost_usd": repo_tokens["api_cost_usd"],
            "pull_requests": len(repo_prs),
        })
    report["by_repo"] = by_repo
    warnings.extend(unpriced_warnings(token_view))
    # gh indisponível em todo repositório repete a mesma frase; deixamos uma por repo.
    report["warnings"] = warnings
    report["caveats"] = build_caveats(report)
    return report


PERIOD_PROMPT = """Qual período? 24 horas, 7 dias, 15 dias ou 30 dias
  1) 24 horas
  2) 7 dias
  3) 15 dias
  4) 30 dias"""


def prompt_period(input_fn=input, output_fn=None) -> str:
    write = output_fn or (lambda text: print(text, file=__import__("sys").stderr))
    write(PERIOD_PROMPT)
    while True:
        answer = normalize_period(input_fn("> "))
        if answer:
            return answer
        write("Não entendi. Responda 1, 2, 3 ou 4 — ou 24 horas, 7 dias, 15 dias, 30 dias.")


def prompt_plan(cfg: dict, input_fn=input, output_fn=None) -> dict:
    write = output_fn or (lambda text: print(text, file=__import__("sys").stderr))
    plans = public_dict(cfg.get("plans", {}))
    write("Qual plano ou licença você usa?")
    if os.environ.get("ANTHROPIC_API_KEY"):
        write("Há uma chave de API no ambiente. Se você paga por token, escolha API sob demanda. A chave não é lida nem impressa.")
    lines = []
    for index, plan_id in enumerate(("api", "pro-monthly", "pro-annual", "max-5x", "max-20x"), start=1):
        plan = plans[plan_id]
        if plan.get("kind") == "metered":
            price = "paga por token"
        else:
            price = format_usd(float(plan["monthly_usd"])) + "/mês"
        lines.append(f"  {index}) {plan['label']} ({price})")
    lines.append("  6) Outro (informe a mensalidade em dólares)")
    write("\n".join(lines))
    mapping = {
        "1": "api",
        "2": "pro-monthly",
        "3": "pro-annual",
        "4": "max-5x",
        "5": "max-20x",
        "6": "custom",
        "api": "api",
        "pro-monthly": "pro-monthly",
        "pro-annual": "pro-annual",
        "max-5x": "max-5x",
        "max-20x": "max-20x",
        "custom": "custom",
    }
    while True:
        choice = mapping.get(input_fn("> ").strip().lower())
        if not choice:
            write("Não entendi. Responda de 1 a 6.")
            continue
        if choice != "custom":
            return plan_spec(cfg, choice, None, None)
        while True:
            raw = input_fn("Mensalidade em dólares (ex.: 20): ").strip().replace(",", ".")
            try:
                monthly = float(raw)
            except ValueError:
                write("Informe um número. Exemplo: 20")
                continue
            if monthly < 0:
                write("A mensalidade não pode ser negativa.")
                continue
            label = input_fn("Nome do plano para o relatório (ex.: outra ferramenta): ").strip()
            return plan_spec(cfg, "custom", monthly, label or "Outro plano")


def resolve_period(explicit: str | None, stdin_is_tty: bool, input_fn=input) -> str:
    if explicit:
        period = normalize_period(explicit)
        if not period:
            raise UsageError(
                f"Período inválido: {explicit}. Use 24h, 7d, 15d ou 30d "
                "(24 horas, 7 dias, 15 dias ou 30 dias)."
            )
        return period
    env_period = os.environ.get("ROT_PERIOD")
    if env_period:
        period = normalize_period(env_period)
        if not period:
            raise UsageError(
                f"ROT_PERIOD inválido: {env_period}. Use 24h, 7d, 15d ou 30d."
            )
        return period
    if stdin_is_tty:
        return prompt_period(input_fn=input_fn)
    raise UsageError(
        "Qual período? 24 horas, 7 dias, 15 dias ou 30 dias.\n"
        "Este terminal não é interativo. Rode de novo com --period 24h, 7d, 15d ou 30d."
    )


def resolve_plan(
    cfg: dict,
    explicit: str | None,
    monthly_usd: float | None,
    label: str | None,
    stdin_is_tty: bool,
    input_fn=input,
) -> dict:
    if explicit:
        try:
            return plan_spec(cfg, explicit, monthly_usd, label)
        except ValueError as exc:
            if str(exc) == "custom-sem-mensalidade":
                raise UsageError(
                    "O plano custom precisa de --monthly-usd com a mensalidade em dólares."
                ) from exc
            raise UsageError(
                f"Plano inválido: {explicit}. Use api, pro-monthly, pro-annual, max-5x, max-20x ou custom."
            ) from exc
    env_plan = os.environ.get("ROT_PLAN") or (cfg.get("default_plan") or "").strip()
    if env_plan:
        try:
            return plan_spec(cfg, env_plan, monthly_usd, label)
        except ValueError as exc:
            raise UsageError(
                f"Plano inválido em ROT_PLAN ou default_plan: {env_plan}."
            ) from exc
    if stdin_is_tty:
        return prompt_plan(cfg, input_fn=input_fn)
    raise UsageError(
        "Qual plano ou licença você usa? API sob demanda, Claude Pro, Claude Max 5x, Claude Max 20x ou outro.\n"
        "Este terminal não é interativo. Rode de novo com --plan api, pro-monthly, pro-annual, max-5x ou max-20x."
    )
