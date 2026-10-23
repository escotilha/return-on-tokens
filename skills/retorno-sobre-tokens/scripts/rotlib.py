#!/usr/bin/env python3
"""Núcleo do ROT — Retorno sobre Tokens.

Mede, num período, as linhas que chegaram ao ramo de produção e os tokens
dos logs locais do Claude Code. O dólar é a moeda base; o real é conversão
opcional por uma taxa editável.

Não estima salário, hora economizada nem ROI de negócio.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

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
    root = Path(result.stdout.strip()).resolve()
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
        "loc": loc,
    }


def collect_git_prs(repo: Path, branch: str, start: dt.datetime, end: dt.datetime, cfg: dict) -> list[dict]:
    found = []
    for commit in iter_first_parent(repo, branch, start, end):
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
                "--json", "number,title,mergedAt,mergeCommit,url",
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
            continue
        if not commit_exists(repo, sha):
            warnings.append(
                f"O PR #{item.get('number')} está mesclado no GitHub, mas o commit "
                f"{str(sha)[:7]} não está neste clone."
            )
            continue
        if not is_ancestor(repo, sha, branch):
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
            prs.append(record)
            by_sha[sha] = record
    return prs, warnings


def lookup_rate(cfg: dict, model: str) -> dict | None:
    models = public_dict(cfg.get("models", {}))
    if model in models:
        return models[model]
    matches = [key for key in models if model.startswith(key)]
    if not matches:
        return None
    return models[max(matches, key=len)]


def price_turn(cfg: dict, model: str, incoming: int, outgoing: int, cache_5m: int, cache_1h: int, cache_read: int) -> tuple[float, str | None]:
    rate = lookup_rate(cfg, model)
    if rate is None:
        return 0.0, model
    prompt = incoming + cache_5m + cache_1h + cache_read
    over = rate.get("when_prompt_over_100k_tokens")
    if isinstance(over, dict) and prompt > 100_000:
        rate = over
    try:
        usd = (
            incoming * float(rate["input"])
            + outgoing * float(rate["output"])
            + cache_5m * float(rate["cache_write_5m"])
            + cache_1h * float(rate["cache_write_1h"])
            + cache_read * float(rate["cache_read"])
        ) / 1_000_000.0
    except (KeyError, TypeError, ValueError):
        return 0.0, model
    return usd, None


def empty_tokens() -> dict:
    return {
        "input": 0,
        "output": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": 0,
        "api_cost_usd": 0.0,
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


def apply_usage(bucket: dict, cfg: dict, model: str, usage: dict) -> None:
    incoming = int(usage.get("input_tokens") or 0)
    outgoing = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_5m, cache_1h = cache_split(usage)
    usd, unpriced = price_turn(cfg, model, incoming, outgoing, cache_5m, cache_1h, cache_read)
    mass = incoming + outgoing + cache_5m + cache_1h + cache_read
    bucket["input"] += incoming
    bucket["output"] += outgoing
    bucket["cache_write_5m"] += cache_5m
    bucket["cache_write_1h"] += cache_1h
    bucket["cache_read"] += cache_read
    bucket["api_cost_usd"] += usd
    bucket["by_model_tokens"][model] = bucket["by_model_tokens"].get(model, 0) + mass
    bucket["by_model_cost_usd"][model] = bucket["by_model_cost_usd"].get(model, 0.0) + usd
    if unpriced and mass:
        bucket["unpriced_tokens"][unpriced] = bucket["unpriced_tokens"].get(unpriced, 0) + mass


def scan_projects(projects_dir: Path, cfg: dict, start: dt.datetime, end: dt.datetime) -> tuple[list[dict], list[str], int]:
    warnings: list[str] = []
    if not projects_dir.is_dir():
        warnings.append(f"Não encontrei logs do Claude Code em {projects_dir}.")
        return [], warnings, 0
    sessions = []
    untimed = 0
    root_cache: dict[str, Path | None] = {}
    for path in sorted(projects_dir.rglob("*.jsonl")):
        if not path.is_file():
            continue
        bucket = empty_tokens()
        mentions: set[int] = set()
        cwd = None
        session_id = None
        moments: list[dt.datetime] = []
        counted = False
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            warnings.append(f"Não consegui ler {path.name}: {exc}")
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("cwd"):
                cwd = str(record["cwd"])
            if record.get("sessionId"):
                session_id = str(record["sessionId"])
            moment = parse_ts(record.get("timestamp"))
            found = usage_from_record(record)
            if found and moment is None:
                untimed += 1
                continue
            if moment is None or moment < start or moment >= end:
                continue
            if record.get("type") == "user":
                for number in PR_MENTION.findall(text_of_user(record)):
                    mentions.add(int(number))
            if not found:
                continue
            apply_usage(bucket, cfg, found["model"], found["usage"])
            moments.append(moment)
            counted = True
        if not counted:
            continue
        root = find_git_root(cwd, root_cache)
        sessions.append({
            "path": str(path),
            "session_id": session_id or path.stem,
            "cwd": cwd,
            "git_root": str(root) if root else None,
            "start": min(moments).isoformat(),
            "end": max(moments).isoformat(),
            "mentions": sorted(mentions),
            "tokens": bucket,
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
    return sessions, warnings, untimed


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
        "O equivalente de API usa a tabela publicada e editável. Modelo sem linha não entra no dólar e aparece nos avisos. Gravação de cache sem o detalhe de 5 minutos ou 1 hora é cobrada como 5 minutos.",
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
            f"O modelo '{model}' não tem preço em rot_config.json — "
            f"{format_int(amount)} tokens ficaram fora do custo em dólares. Acrescente uma linha na tabela para precificá-los."
        )
    return warnings


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
    rows = [
        ("Entrada", tokens["input"]),
        ("Saída", tokens["output"]),
        ("Gravação de cache (5 min)", tokens["cache_write_5m"]),
        ("Gravação de cache (1 h)", tokens["cache_write_1h"]),
        ("Leitura de cache", tokens["cache_read"]),
        ("Total", tokens["total"]),
    ]
    for label, amount in rows:
        lines.append(f"  {label:<32}{format_int(amount):>14}")
    lines.append(f"  {'Sessões no período':<32}{format_int(report['sessions']):>14}")
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
    lines.append("")
    lines.append("CUSTO")
    lines.append(f"  {'Equivalente de API':<32}{format_usd(cost['api_equivalent_usd']):>18}")
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
    lines.append(f"  {'Linhas efetivas por milhão de tokens':<52}{_fmt_optional_number(ratios['effective_loc_per_million_tokens'])}")
    lines.append(
        f"  {'Idem, só repositórios que publicaram':<52}"
        f"{_fmt_optional_number(ratios['effective_loc_per_million_shipping_tokens'])}"
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
            lines.append(f"  ! {warning}")
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
            root = path
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
) -> dict:
    start, end = period_bounds(period_id, now)
    sessions, warnings, _untimed = scan_projects(projects_dir, config, start, end)
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
        pull_requests.extend(prs)
        repo_rows.append({
            "name": repo.name,
            "path": str(repo),
            "branch": chosen_branch,
            "source": source,
        })

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
            "effective_loc_per_million_tokens": ratio(effective, token_view["total"] / 1_000_000) if token_view["total"] else None,
            "effective_loc_per_million_shipping_tokens": (
                ratio(effective, shipping_view["total"] / 1_000_000) if shipping_view["total"] else None
            ),
        },
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
